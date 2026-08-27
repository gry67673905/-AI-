from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from app.application.dtos import DocumentFrameData, Principal
from app.application.metastudio import MetaStudioChatCommand, MetaStudioTurn
from app.boundaries.http import current_principal, optional_principal
from app.boundaries.metastudio_schemas import (
    MetaStudioClientSessionRequest,
    MetaStudioClientSessionResponse,
    MetaStudioIntentExchangeRequest,
    MetaStudioIntentExchangeResponse,
    MetaStudioLlmRequest,
    MetaStudioVisionSessionRequest,
    MetaStudioVisionSessionResponse,
)
from app.boundaries.vision_protocol import (
    VisionProtocolError,
    binary_packet_type,
    parse_control_message,
    parse_document_frame_packet,
    parse_frame_packet,
)
from app.application.vision import DocumentAnalysisError
from app.errors import DependencyUnavailable

logger = logging.getLogger(__name__)

_SAFE_DIAGNOSTIC_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}")
_MAX_DIAGNOSTIC_FIELDS = 32
_MAX_DIAGNOSTIC_MESSAGES = 9
_MAX_DIAGNOSTIC_ERRORS = 20


def _compact_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=str
    )


def _diagnostic_name(value: Any) -> str:
    if isinstance(value, str) and _SAFE_DIAGNOSTIC_NAME.fullmatch(value):
        return value
    return "<unsafe>"


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "other"


def _field_shapes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    shapes: list[dict[str, Any]] = []
    for name, field_value in list(value.items())[:_MAX_DIAGNOSTIC_FIELDS]:
        item: dict[str, Any] = {
            "name": _diagnostic_name(name),
            "type": _json_type(field_value),
        }
        if isinstance(field_value, list):
            item["length"] = len(field_value)
        shapes.append(item)
    return shapes


def _callback_request_shape(raw: Any) -> dict[str, Any]:
    """Describe callback structure without retaining any field value."""

    shape: dict[str, Any] = {"root_type": _json_type(raw)}
    if not isinstance(raw, dict):
        return shape
    shape["fields"] = _field_shapes(raw)
    shape["fields_truncated"] = len(raw) > _MAX_DIAGNOSTIC_FIELDS

    messages = raw.get("messages")
    if isinstance(messages, list):
        shape["messages"] = {
            "length": len(messages),
            "items": [
                {
                    "index": index,
                    "type": _json_type(item),
                    "fields": _field_shapes(item),
                }
                for index, item in enumerate(
                    messages[:_MAX_DIAGNOSTIC_MESSAGES]
                )
            ],
            "items_truncated": len(messages) > _MAX_DIAGNOSTIC_MESSAGES,
        }

    extend_param = raw.get("extend_param")
    if isinstance(extend_param, dict):
        shape["extend_param"] = {"fields": _field_shapes(extend_param)}
    return shape


def _validation_error_shape(exc: ValidationError) -> list[dict[str, Any]]:
    """Return only Pydantic locations and machine-readable error types."""

    result: list[dict[str, Any]] = []
    errors = exc.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )
    for error in errors[:_MAX_DIAGNOSTIC_ERRORS]:
        location: list[str | int] = []
        for part in tuple(error.get("loc", ()))[:8]:
            if isinstance(part, int):
                location.append(part)
            else:
                location.append(_diagnostic_name(part))
        result.append(
            {
                "loc": location,
                "type": _diagnostic_name(error.get("type")),
            }
        )
    if len(errors) > _MAX_DIAGNOSTIC_ERRORS:
        result.append({"loc": [], "type": "errors_truncated"})
    return result


async def _log_authenticated_schema_failure(
    request: Request,
    raw: Any,
    exc: ValidationError,
    secret: str | None,
    time_stamp: str | None,
) -> None:
    """Log a value-free diagnostic only for an authentic vendor callback."""

    if not secret or not time_stamp or not isinstance(raw, dict):
        return
    app_id = raw.get("app_id")
    if not isinstance(app_id, str) or not 1 <= len(app_id) <= 128:
        return
    try:
        verified = await _runtime(request).metastudio_authenticator.verify(
            secret, time_stamp, app_id
        )
    except Exception:
        # Diagnostics must not alter the established safe 400 response for an
        # invalid payload when replay storage or another auth dependency is
        # unavailable.
        return
    if not verified:
        return
    diagnostic = {
        "shape": _callback_request_shape(raw),
        "errors": _validation_error_shape(exc),
    }
    logger.warning(
        "metastudio_callback_schema_rejected diagnostic=%s",
        _compact_json(diagnostic),
    )


def _metastudio_error(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error_code": code, "error_msg": message},
    )


def _runtime(request: Request) -> Any:
    return request.app.state.services.business


class MetaStudioHttpBoundary:
    _VISION_WS_PATH = "/api/v1/integrations/metastudio/vision/ws"

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/integrations/metastudio", tags=["MetaStudio"])
        self.router.add_api_route("/llm", self.llm, methods=["POST"])
        self.router.add_api_route(
            "/client-sessions",
            self.client_session,
            methods=["POST"],
            response_model=MetaStudioClientSessionResponse,
            responses={503: {"description": "MetaStudio凭据或依赖未就绪"}},
        )
        self.router.add_api_route(
            "/action-intents/{intent_id}/exchange",
            self.exchange_intent,
            methods=["POST"],
            response_model=MetaStudioIntentExchangeResponse,
        )
        self.router.add_api_route(
            "/vision-sessions",
            self.vision_session,
            methods=["POST"],
            response_model=MetaStudioVisionSessionResponse,
            responses={503: {"description": "视觉服务未启用或依赖不可用"}},
        )
        self.router.add_api_websocket_route("/vision/ws", self.vision_ws)

    async def llm(
        self,
        request: Request,
        secret: Annotated[str | None, Query()] = None,
        time_stamp: Annotated[str | None, Query()] = None,
    ) -> Response:
        try:
            content_length = int(request.headers.get("content-length", "0") or "0")
            if content_length > 128 * 1024:
                raise ValueError("request too large")
            body = await request.body()
            if len(body) > 128 * 1024:
                raise ValueError("request too large")
            raw = json.loads(body)
            payload = MetaStudioLlmRequest.model_validate(raw)
        except ValidationError as exc:
            await _log_authenticated_schema_failure(
                request, raw, exc, secret, time_stamp
            )
            return _metastudio_error(
                "METASTUDIO.INVALID_REQUEST", "Invalid request"
            )
        except (ValueError, TypeError):
            return _metastudio_error(
                "METASTUDIO.INVALID_REQUEST", "Invalid request"
            )

        runtime = _runtime(request)
        if not secret or not time_stamp:
            return _metastudio_error(
                "METASTUDIO.AUTH_FAILED", "Authentication failed"
            )
        verified = await runtime.metastudio_authenticator.verify(
            secret, time_stamp, payload.app_id
        )
        if not verified:
            return _metastudio_error(
                "METASTUDIO.AUTH_FAILED", "Authentication failed"
            )

        command = MetaStudioChatCommand(
            messages=tuple(MetaStudioTurn(item.content) for item in payload.messages),
            app_id=payload.app_id,
            user=payload.user,
            chat_id=payload.session_id,
            is_stream=payload.is_stream,
            client_id=(
                payload.extend_param.client_id if payload.extend_param else None
            ),
        )
        quota = getattr(request.app.state.services, "chat_quota", None)
        if quota is not None:
            quota_subject, client_quota_key = await runtime.metastudio.quota_identity(
                command.client_id
            )
            await quota.consume(
                quota_subject,
                # A missing/expired client context must not let a provider-
                # generated anonymous user value mint a fresh quota subject
                # after every activity re-entry. Keep all unbound callbacks in
                # one conservative bucket; valid clients retain their stable
                # account/IP-derived pseudonym above.
                client_quota_key or "metastudio-provider:unbound",
            )
        if payload.is_stream:
            return self._stream(runtime.metastudio, command)

        answer = await runtime.metastudio.answer(command)
        message: dict[str, Any] = {"content": answer.content}
        if answer.extend_param is not None:
            message["extend_param"] = answer.extend_param
        body = {
            "id": answer.response_id,
            "created": answer.created,
            "choices": [{"index": 0, "message": message}],
        }
        return Response(
            content=_compact_json(body),
            status_code=200,
            media_type="application/json;charset=UTF-8",
        )

    @staticmethod
    def _stream(coordinator: Any, command: MetaStudioChatCommand) -> StreamingResponse:
        async def events():
            stream_id = uuid4().hex
            queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

            async def emit(delta: str) -> None:
                await queue.put(("delta", delta))

            async def produce() -> None:
                try:
                    result = await coordinator.answer(command, on_delta=emit)
                    await queue.put(("done", result))
                except Exception as exc:
                    await queue.put(("error", exc))

            producer = asyncio.create_task(produce(), name="metastudio-llm-stream")
            pending_delta: str | None = None

            def frame(content: str, extend_param: str | None = None) -> str:
                message: dict[str, str] = {"content": content}
                if extend_param is not None:
                    message["extend_param"] = extend_param
                payload = {
                    "id": stream_id,
                    "created": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "choices": [{"message": message}],
                }
                return f"data:{_compact_json(payload)}\n\n"

            try:
                while True:
                    kind, value = await queue.get()
                    if kind == "delta":
                        # Hold one delta so extend_param can accompany the final
                        # real text chunk instead of an artificial spoken token.
                        if pending_delta is not None:
                            yield frame(pending_delta)
                        pending_delta = value
                        continue
                    if kind == "done":
                        final_content = pending_delta or value.content
                        if final_content:
                            yield frame(final_content, value.extend_param)
                        yield "data:[DONE]\n\n"
                        break
                    if pending_delta is not None:
                        yield frame(pending_delta)
                    yield frame("智能问答服务暂不可用，请稍后重试。")
                    yield "data:[DONE]\n\n"
                    break
            finally:
                if not producer.done():
                    producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)

        return StreamingResponse(
            events(),
            media_type="text/event-stream;charset=UTF-8",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def client_session(
        self,
        _payload: MetaStudioClientSessionRequest,
        request: Request,
        principal: Annotated[Principal | None, Depends(optional_principal)],
    ) -> dict[str, Any]:
        quota = getattr(request.app.state.services, "metastudio_session_quota", None)
        client_ip = request.client.host if request.client is not None else "unknown"
        if quota is not None:
            await quota.consume(
                principal.account_id if principal is not None else None,
                client_ip,
            )
        return await _runtime(request).metastudio.create_client_session(
            principal, client_ip
        )

    async def exchange_intent(
        self,
        intent_id: UUID,
        payload: MetaStudioIntentExchangeRequest,
        request: Request,
        principal: Annotated[Principal | None, Depends(optional_principal)],
    ) -> dict[str, Any]:
        return await _runtime(request).metastudio.exchange_intent(
            principal, intent_id, payload.session_id, payload.chat_id
        )

    async def vision_session(
        self,
        payload: MetaStudioVisionSessionRequest,
        request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> dict[str, Any]:
        runtime = _runtime(request)
        callback_url = urlsplit(runtime.settings.metastudio_callback_url)
        if (
            callback_url.scheme.lower() != "https"
            or callback_url.hostname is None
            or callback_url.username is not None
            or callback_url.password is not None
        ):
            raise DependencyUnavailable("metastudio_vision")
        websocket_url = urlunsplit(
            ("wss", callback_url.netloc, self._VISION_WS_PATH, "", "")
        )
        # Validate the public WSS origin before minting a one-use ticket so a
        # broken deployment cannot leave partially usable credentials behind.
        bundle = await runtime.metastudio.create_vision_session(
            principal, payload.client_session_id
        )
        return {
            "vision_session_id": bundle.vision_session_id,
            "vision_websocket_url": websocket_url,
            "vision_token": bundle.vision_token,
            "vision_expires_at": bundle.vision_expires_at,
        }

    @staticmethod
    async def _vision_error(websocket: WebSocket, code: str) -> None:
        await websocket.send_json({"v": 1, "type": "vision.error", "code": code})

    async def vision_ws(self, websocket: WebSocket) -> None:
        runtime = websocket.app.state.services.business
        authorization = websocket.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token:
            await websocket.close(code=4401, reason="vision_auth_failed")
            return
        try:
            claims = await runtime.vision.consume_ticket(token)
            if claims is None or not await runtime.metastudio.authorize_vision_claim(claims):
                await websocket.close(code=4401, reason="vision_auth_failed")
                return
        except Exception:
            await websocket.close(code=1011, reason="vision_dependency_unavailable")
            return

        await websocket.accept()
        started = False
        active_turn: int | None = None
        active_document: int | None = None
        document_sequences: set[int] = set()
        document_sequence_limit = 32
        document_task: asyncio.Task[None] | None = None
        send_lock = asyncio.Lock()
        invalid_messages = 0
        settings = runtime.settings

        async def send_json(payload: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(payload)

        async def analyze_document(frame: DocumentFrameData) -> None:
            try:
                await runtime.vision.analyze_document(claims, frame)
            except DocumentAnalysisError as exc:
                await send_json(
                    {
                        "v": 1,
                        "type": "document.error",
                        "document_seq": frame.document_sequence,
                        "code": exc.code,
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                await send_json(
                    {
                        "v": 1,
                        "type": "document.error",
                        "document_seq": frame.document_sequence,
                        "code": "analysis_unavailable",
                    }
                )
            else:
                # OCR text is deliberately not returned over WSS. The next
                # signed MetaStudio turn consumes the short-lived context.
                await send_json(
                    {
                        "v": 1,
                        "type": "document.ready",
                        "document_seq": frame.document_sequence,
                    }
                )
            finally:
                frame = None

        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                text_message = message.get("text")
                binary_message = message.get("bytes")
                frame = None
                document_frame = None
                document_state_reason: str | None = None
                try:
                    if text_message is not None:
                        control = parse_control_message(text_message)
                        message_type = control["type"]
                        if not started:
                            if message_type != "vision.start":
                                raise VisionProtocolError("vision_start_required")
                            if (
                                control["vision_session_id"] != claims.vision_session_id
                                or control["client_session_id"]
                                != claims.client_session_id
                            ):
                                raise VisionProtocolError("session_mismatch")
                            if not await runtime.vision.register_session(claims):
                                raise VisionProtocolError("vision_session_active")
                            started = True
                            await send_json(
                                {"v": 1, "type": "vision.started"}
                            )
                            continue
                        if message_type == "vision.start":
                            raise VisionProtocolError("duplicate_start")
                        if message_type == "document.start":
                            document_sequence = control["document_seq"]
                            # Preserve the single public protocol error while
                            # recording only a fixed, value-free reason.  This
                            # makes live failures diagnosable without logging
                            # sequence/session IDs, request contents, tickets,
                            # or Authorization headers.
                            if active_turn is not None:
                                document_state_reason = "active_turn"
                            elif active_document is not None:
                                document_state_reason = "active_document"
                            elif (
                                document_task is not None
                                and not document_task.done()
                            ):
                                document_state_reason = "document_task"
                            elif document_sequence in document_sequences:
                                document_state_reason = "duplicate_sequence"
                            elif len(document_sequences) >= document_sequence_limit:
                                document_state_reason = "sequence_limit"
                            if document_state_reason is not None:
                                raise VisionProtocolError("invalid_document_state")
                            if not await runtime.vision.start_document(
                                claims, document_sequence
                            ):
                                document_state_reason = "coordinator_rejected"
                                raise VisionProtocolError("invalid_document_state")
                            active_document = document_sequence
                            await send_json(
                                {
                                    "v": 1,
                                    "type": "document.started",
                                    "document_seq": document_sequence,
                                }
                            )
                            continue
                        turn_sequence = control["turn_seq"]
                        if message_type == "turn.start":
                            if (
                                active_turn is not None
                                or active_document is not None
                                or (
                                    document_task is not None
                                    and not document_task.done()
                                )
                                or not await runtime.vision.start_turn(
                                    claims, turn_sequence
                                )
                            ):
                                raise VisionProtocolError("invalid_turn_state")
                            active_turn = turn_sequence
                            await send_json(
                                {
                                    "v": 1,
                                    "type": "turn.started",
                                    "turn_seq": turn_sequence,
                                }
                            )
                            continue
                        if active_turn != turn_sequence or not await runtime.vision.end_turn(
                            claims, turn_sequence
                        ):
                            raise VisionProtocolError("invalid_turn_state")
                        active_turn = None
                        await send_json(
                            {
                                "v": 1,
                                "type": "turn.ended",
                                "turn_seq": turn_sequence,
                            }
                        )
                        continue

                    if binary_message is None or not started:
                        raise VisionProtocolError("vision_start_required")
                    packet_type = binary_packet_type(binary_message)
                    if packet_type == "document.frame":
                        if active_document is None:
                            raise VisionProtocolError("document_start_required")
                        document_frame = parse_document_frame_packet(
                            binary_message,
                            claims,
                            max_frame_bytes=1024 * 1024,
                            max_dimension=2048,
                            max_clock_skew_seconds=settings.vision_clock_skew_seconds,
                        )
                        if document_frame.document_sequence != active_document:
                            raise VisionProtocolError("document_mismatch")
                        # Value-free capture telemetry is enough to distinguish
                        # an unreadable source photo from transport/schema
                        # failures.  Never log the JPEG, OCR text, ticket,
                        # session identifiers, or request headers.
                        logger.info(
                            "vision_protocol stage=document_frame status=accepted "
                            "width=%d height=%d jpeg_bytes=%d camera=%s",
                            document_frame.width,
                            document_frame.height,
                            len(document_frame.jpeg),
                            document_frame.camera,
                        )
                        document_sequence = active_document
                        active_document = None
                        document_sequences.add(document_sequence)
                        # Receipt is acknowledged before starting the one paid
                        # provider call, keeping UI and inference independent.
                        await send_json(
                            {
                                "v": 1,
                                "type": "document.ack",
                                "document_seq": document_sequence,
                                "status": "accepted",
                            }
                        )
                        document_task = asyncio.create_task(
                            analyze_document(document_frame),
                            name="metastudio-document-analysis",
                        )
                        document_task.add_done_callback(
                            lambda completed: (
                                None
                                if completed.cancelled()
                                else completed.exception()
                            )
                        )
                        document_frame = None
                        continue
                    if active_turn is None:
                        raise VisionProtocolError("turn_start_required")
                    frame = parse_frame_packet(
                        binary_message,
                        claims,
                        max_frame_bytes=settings.vision_max_frame_bytes,
                        max_width=settings.vision_max_dimension,
                        max_height=settings.vision_max_dimension,
                        max_clock_skew_seconds=settings.vision_clock_skew_seconds,
                    )
                    if frame.turn_sequence != active_turn:
                        raise VisionProtocolError("turn_mismatch")
                    result = await runtime.vision.ingest(claims, frame)
                    if result not in {"accepted", "frame_rate_limited"}:
                        raise VisionProtocolError(result)
                    await send_json(
                        {
                            "v": 1,
                            "type": "vision.ack",
                            "turn_seq": frame.turn_sequence,
                            "frame_seq": frame.frame_sequence,
                            "status": (
                                "accepted"
                                if result == "accepted"
                                else "dropped"
                            ),
                        }
                    )
                except VisionProtocolError as exc:
                    invalid_messages += 1
                    # The category is drawn from the protocol parser's fixed,
                    # non-secret vocabulary.  Keep enough telemetry to
                    # distinguish a rejected control from a malformed JPEG
                    # without ever logging headers, tickets or image bytes.
                    if (
                        exc.code == "invalid_document_state"
                        and document_state_reason is not None
                    ):
                        logger.warning(
                            "vision_protocol stage=message status=rejected "
                            "category=%s reason=%s",
                            _diagnostic_name(exc.code),
                            _diagnostic_name(document_state_reason),
                        )
                    else:
                        logger.warning(
                            "vision_protocol stage=message status=rejected category=%s",
                            _diagnostic_name(exc.code),
                        )
                    await send_json(
                        {"v": 1, "type": "vision.error", "code": exc.code}
                    )
                    if invalid_messages >= 3:
                        await websocket.close(code=4400, reason="vision_protocol_error")
                        return
                finally:
                    # Do not let the coroutine's last loop locals pin a raw
                    # packet after the frame store's independent TTL sweeper
                    # has removed it while this socket remains idle.
                    frame = None
                    document_frame = None
                    binary_message = None
                    text_message = None
                    message = None
        except WebSocketDisconnect:
            return
        finally:
            if document_task is not None:
                if not document_task.done():
                    document_task.cancel()
                await asyncio.gather(document_task, return_exceptions=True)
            if started:
                try:
                    await runtime.vision.discard_session(
                        claims,
                        # A short no-bytes generation tombstone prevents an old
                        # in-flight callback from binding to a replacement WSS.
                        # It is consumed by that callback or expires by TTL.
                        mark_unavailable=True,
                    )
                except Exception:
                    pass
