from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from app.application.dtos import Principal
from app.application.metastudio import MetaStudioChatCommand, MetaStudioTurn
from app.boundaries.http import current_principal, optional_principal
from app.boundaries.metastudio_schemas import (
    MetaStudioClientSessionRequest,
    MetaStudioClientSessionResponse,
    MetaStudioIntentExchangeRequest,
    MetaStudioIntentExchangeResponse,
    MetaStudioLlmRequest,
)

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
            anonymous_key = hashlib.sha256(
                f"{payload.app_id}:{payload.user}".encode("utf-8")
            ).hexdigest()[:32]
            await quota.consume(
                quota_subject,
                client_quota_key or f"metastudio-provider:{anonymous_key}",
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
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> dict[str, Any]:
        return await _runtime(request).metastudio.exchange_intent(
            principal, intent_id, payload.session_id, payload.chat_id
        )
