from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.application.coordinators import ConsultationCoordinator
from app.application.dtos import (
    ChatCommand,
    ChatResult,
    ConversationMessageData,
    Principal,
    VisionTicketClaimsData,
)
from app.application.ports import (
    BusinessRepositoryPort,
    MetaStudioOnceCodePort,
    MetaStudioSessionPort,
)
from app.domain.enums import ApplicantType, Role
from app.domain.policies import DigitalHumanIntentPolicy
from app.errors import AuthenticationRequired, DependencyUnavailable, ResourceNotFound
from app.application.vision import VisionCoordinator, VisionSessionBundle


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MetaStudioTurn:
    content: str


@dataclass(frozen=True, slots=True)
class MetaStudioChatCommand:
    messages: tuple[MetaStudioTurn, ...]
    app_id: str
    user: str
    chat_id: str
    is_stream: bool
    client_id: str | None


@dataclass(frozen=True, slots=True)
class MetaStudioAnswer:
    response_id: str
    created: int
    content: str
    extend_param: str | None
    chat_result: ChatResult


class MetaStudioCoordinator:
    """Coordinate the digital-human channel without granting mutation power."""

    _LAUNCH_TTL_SECONDS = 300
    _PUBLIC_NAVIGATION_INTENT = DigitalHumanIntentPolicy.SERVICE_NAVIGATION_INTENT
    def __init__(
        self,
        repository: BusinessRepositoryPort,
        consultations: ConsultationCoordinator,
        sessions: MetaStudioSessionPort,
        once_codes: MetaStudioOnceCodePort,
        *,
        pii_hmac_key: str,
        robot_id: str | None,
        server_address: str,
        context_ttl_seconds: int,
        action_intent_ttl_seconds: int,
        vision: VisionCoordinator | None = None,
    ) -> None:
        self.repository = repository
        self.consultations = consultations
        self.sessions = sessions
        self.once_codes = once_codes
        self._pii_hmac_key = pii_hmac_key.encode("utf-8")
        self._robot_id = robot_id or ""
        self._server_address = server_address
        self._context_ttl_seconds = context_ttl_seconds
        self._action_intent_ttl_seconds = action_intent_ttl_seconds
        self.vision = vision
        self._intent_policy = DigitalHumanIntentPolicy()

    def _opaque_hash(self, category: str, value: str) -> str:
        return hmac.new(
            self._pii_hmac_key,
            f"{category}:{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def create_client_session(
        self, principal: Principal | None, origin_ip: str
    ) -> dict[str, Any]:
        if not self._robot_id or not self._valid_server_address():
            raise DependencyUnavailable("metastudio")
        session_id = uuid4()
        identity = str(principal.account_id) if principal is not None else str(session_id)
        app_user_id = f"gov_{self._opaque_hash('app-user', identity)[:32]}"
        issued_at = datetime.now(timezone.utc)
        # No Redis session is created unless Huawei successfully returns a code;
        # this avoids handing Android a partially usable launch bundle.
        once_code = await self.once_codes.create_once_code(app_user_id)
        # The launch bundle follows Huawei's five-minute onceCode lifetime, but
        # the callback context must outlive SDK startup and the full dialogue.
        launch_expires_at = issued_at + timedelta(seconds=self._LAUNCH_TTL_SECONDS)
        context_expires_at = issued_at + timedelta(seconds=self._context_ttl_seconds)
        values: dict[str, Any] = {
            "context_expires_at": context_expires_at.isoformat(),
            "account_id": str(principal.account_id) if principal else None,
            "role": principal.role.value if principal else None,
            "applicant_type": (
                principal.applicant_type.value
                if principal and principal.applicant_type
                else None
            ),
            "token_version": principal.token_version if principal else None,
            "department_id": (
                str(principal.department_id)
                if principal and principal.department_id
                else None
            ),
            # Retain only an HMAC pseudonym. Provider callbacks originate from
            # Huawei infrastructure, so this binds anonymous LLM quota to the
            # Android client that obtained the onceCode without storing its IP.
            "anonymous_quota_key": self._opaque_hash(
                "client-ip", origin_ip or "unknown"
            ),
        }
        try:
            remaining_ttl = max(
                1,
                int((context_expires_at - datetime.now(timezone.utc)).total_seconds()),
            )
            await self.sessions.put(
                session_id, values, remaining_ttl
            )
        except Exception as exc:
            raise DependencyUnavailable("metastudio_session") from exc
        return {
            "session_id": session_id,
            "once_code": once_code,
            "robot_id": self._robot_id,
            "server_address": self._server_address,
            "expires_at": launch_expires_at,
        }

    async def answer(
        self,
        command: MetaStudioChatCommand,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> MetaStudioAnswer:
        safe_messages = tuple(
            self.consultations.security.redact_public_text(item.content)
            for item in command.messages[-9:]
        )
        current_question = safe_messages[-1]
        conversation_history = tuple(
            ConversationMessageData(
                role=(
                    "human"
                    if (len(safe_messages) - 1 - index) % 2 == 0
                    else "ai"
                ),
                content=content,
            )
            for index, content in enumerate(safe_messages[:-1])
        )
        principal, client_session_id, _ = await self._client_context(command.client_id)
        internal_session_id = uuid5(
            NAMESPACE_URL, f"smart-gov:metastudio:{command.app_id}:{command.chat_id}"
        )

        emitted_count = 0

        async def bounded_delta(value: str) -> None:
            nonlocal emitted_count
            if on_delta is None or emitted_count >= 4096:
                return
            remaining = 4096 - emitted_count
            delta = value[:remaining]
            if delta:
                emitted_count += len(delta)
                await on_delta(delta)

        visual_context = None
        document_context = None
        visual_warning: str | None = None
        document_capture_request = ConsultationCoordinator.is_document_capture_request(
            current_question
        )
        document_followup = ConsultationCoordinator.is_document_followup_question(
            current_question
        )
        if principal is not None and client_session_id is not None and self.vision is not None:
            try:
                await self.vision.note_chat(client_session_id, command.chat_id)
                if document_capture_request:
                    # A new capture request always invalidates the previous
                    # photo before the fixed guidance is returned.
                    await self.vision.clear_document_context(client_session_id)
                elif document_followup:
                    document_context = await self.vision.get_document_context(
                        client_session_id, command.chat_id
                    )
            except Exception:
                logger.warning(
                    "document_fusion stage=context status=failed "
                    "category=coordinator_exception"
                )
            else:
                logger.info(
                    "document_fusion stage=context status=%s category=%s",
                    "attached" if document_context is not None else "skipped",
                    "available" if document_context is not None else "not_present",
                )
            try:
                if document_capture_request or document_context is not None:
                    # A request to read a file begins with guided capture. Do
                    # not spend a normal low-resolution scene-analysis call on
                    # it; only an explicit document photo may invoke OCR.
                    visual_context = None
                    await self.vision.discard_latest_scene_turn(
                        client_session_id
                    )
                else:
                    visual_context = await self.vision.analyze_latest_turn(
                        client_session_id, current_question
                    )
            except Exception:
                # Vision is optional and must never make the signed MetaStudio
                # callback unavailable. Raw frames were already popped by the
                # bounded store before an analyzer can fail.
                logger.warning(
                    "vision_fusion stage=context status=failed "
                    "category=coordinator_exception"
                )
                visual_warning = (
                    "visual_unavailable: 本轮视觉信息不可用，已继续处理用户问题"
                )
            else:
                if visual_context is None:
                    status, category = "skipped", "not_present"
                elif visual_context.available:
                    status, category = "attached", "available"
                else:
                    status, category = "degraded", "unavailable"
                    visual_context = None
                    visual_warning = (
                        "visual_unavailable: 本轮视觉信息不可用，已继续处理用户问题"
                    )
                logger.info(
                    "vision_fusion stage=context status=%s category=%s",
                    status,
                    category,
                )

        result = await self.consultations.chat(
            ChatCommand(
                message=current_question,
                session_id=internal_session_id,
                conversation_history=conversation_history,
                visual_context=visual_context,
                document_context=document_context,
            ),
            principal,
            on_delta=bounded_delta if on_delta is not None else None,
        )
        if visual_warning is not None and visual_warning not in result.warnings:
            result.warnings.append(visual_warning)
            logger.info(
                "vision_fusion stage=turn status=continued "
                "category=visual_unavailable"
            )
        content = result.answer[:4096]
        safe_suggested_actions = result.suggested_actions
        if (
            (visual_context is not None and visual_context.available)
            or document_context is not None
        ):
            # The answer may use allowlisted visual hints for public
            # catalogue/RAG lookup. Re-resolve action candidates from the
            # current spoken question only, so camera content can neither
            # create nor suppress an otherwise valid voice navigation intent.
            speech_resolver = getattr(
                self.consultations, "actions_for_current_question", None
            )
            if callable(speech_resolver):
                try:
                    safe_suggested_actions = await speech_resolver(current_question)
                except Exception:
                    safe_suggested_actions = []
            else:
                safe_suggested_actions = []
        navigation_option = await self._navigation_option_for_actions(
            safe_suggested_actions
        )
        proposal = self._intent_policy.propose(
            current_question,
            principal.role if principal else None,
            # These candidates were resolved from current speech only whenever
            # visual context participated in the answer.
            safe_suggested_actions,
            navigation_option=navigation_option,
        )
        extend_param: str | None = None
        if proposal is not None and client_session_id is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=self._action_intent_ttl_seconds
            )
            intent = await self.repository.create_digital_human_intent(
                principal.account_id if principal else None,
                principal.role if principal else None,
                client_session_id,
                # MetaStudio's callback session_id identifies the provider
                # conversation. It is deliberately not confused with the
                # per-turn semanticRecognized.chatId returned to Android.
                self._opaque_hash("provider-session", command.chat_id),
                proposal.intent_type,
                proposal.label,
                proposal.section,
                proposal.prefill,
                expires_at,
            )
            extend_param = json.dumps(
                {
                    "v": 1,
                    "intent_id": str(intent["id"]),
                    "type": intent["type"],
                    "label": intent["label"],
                    "expires_at": intent["expires_at"].isoformat(),
                    "requires_confirmation": True,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return MetaStudioAnswer(
            response_id=uuid4().hex,
            # Huawei's current non-stream example uses yyyyMMddHHmmss, while
            # its stream frames use Unix milliseconds.  The boundary generates
            # stream timestamps independently.
            created=int(datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")),
            content=content,
            extend_param=extend_param,
            chat_result=result,
        )

    async def authorize_client_session(
        self, principal: Principal, client_session_id: UUID
    ) -> None:
        session_principal, live_session_id, _ = await self._client_context(
            str(client_session_id)
        )
        if (
            session_principal is None
            or live_session_id != client_session_id
            or session_principal.account_id != principal.account_id
            or session_principal.role != principal.role
            or session_principal.token_version != principal.token_version
        ):
            # Conceal whether a UUID belongs to another account or expired.
            raise ResourceNotFound("数字人客户端会话")

    async def create_vision_session(
        self, principal: Principal, client_session_id: UUID
    ) -> VisionSessionBundle:
        if self.vision is None:
            raise DependencyUnavailable("metastudio_vision")
        return await self.vision.create_session(principal, client_session_id)

    async def authorize_vision_claim(
        self, claims: VisionTicketClaimsData
    ) -> bool:
        principal, live_session_id, _ = await self._client_context(
            str(claims.client_session_id)
        )
        return bool(
            principal is not None
            and live_session_id == claims.client_session_id
            and principal.account_id == claims.account_id
            and principal.role == claims.role
            and principal.token_version == claims.token_version
        )

    async def exchange_intent(
        self,
        principal: Principal | None,
        intent_id: UUID,
        client_session_id: UUID,
        chat_id: str,
    ) -> dict[str, Any]:
        session_principal, live_session_id, session_values = await self._client_context(
            str(client_session_id)
        )
        if live_session_id != client_session_id or session_values is None:
            # Conceal whether either the intent or a stale/cross-account
            # client session exists.
            raise ResourceNotFound("数字人操作意图")
        if principal is None:
            if session_principal is not None or not self._valid_anonymous_values(
                session_values
            ):
                raise ResourceNotFound("数字人操作意图")
            actor_id = None
            actor_role = None
        else:
            if (
                session_principal is None
                or session_principal.account_id != principal.account_id
                or session_principal.role != principal.role
                or session_principal.token_version != principal.token_version
            ):
                raise ResourceNotFound("数字人操作意图")
            actor_id = principal.account_id
            actor_role = principal.role
        try:
            values = await self.repository.consume_digital_human_intent(
                intent_id,
                actor_id,
                actor_role,
                client_session_id,
                self._opaque_hash("client-chat", chat_id),
                datetime.now(timezone.utc),
                required_intent_type=(
                    self._PUBLIC_NAVIGATION_INTENT
                    if principal is None
                    else None
                ),
            )
        except ResourceNotFound:
            raise
        if principal is None and values.get("type") != self._PUBLIC_NAVIGATION_INTENT:
            # Anonymous users may exchange the one public, read-only
            # navigation proposal only. All other workbench intents retain the
            # existing login boundary.
            raise AuthenticationRequired("请先登录后继续")
        if values.get("type") == self._PUBLIC_NAVIGATION_INTENT:
            values = await self._validate_navigation_exchange(intent_id, values)
        return {**values, "requires_confirmation": True}

    async def _navigation_option_for_actions(
        self, suggested_actions: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Load server-owned handling state for one deterministic candidate."""

        if len(suggested_actions) != 1:
            return None
        action = suggested_actions[0]
        if action.get("type") != "VIEW_SERVICE":
            return None
        try:
            service_id = UUID(str(action.get("service_id", "")))
        except (ValueError, TypeError, AttributeError):
            return None
        resolver = getattr(self.repository, "get_navigation_options", None)
        if not callable(resolver):
            return None
        try:
            raw = await resolver(service_id)
        except Exception:
            # Navigation is an optional read-only suggestion. Catalogue
            # degradation must not make the signed LLM callback unavailable.
            return None
        return self._normalize_navigation_option(service_id, raw)

    @staticmethod
    def _normalize_navigation_option(
        service_id: UUID, raw: object
    ) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        service = raw.get("service")
        if not isinstance(service, dict):
            return None
        try:
            returned_service_id = UUID(str(service.get("id", "")))
        except (ValueError, TypeError, AttributeError):
            return None
        if returned_service_id != service_id:
            return None
        windows = raw.get("windows")
        if not isinstance(windows, list):
            return None
        # get_navigation_options rejects non-PUBLISHED services and returns
        # active links/windows only. Requiring a non-empty list here makes the
        # application fail closed if that projection is unavailable or changes
        # shape.
        return {
            "service_id": str(service_id),
            "published": True,
            "has_active_locations": bool(windows),
            "handling_mode": str(service.get("handling_mode", "UNKNOWN")).upper(),
            "online_status": str(service.get("online_status", "UNKNOWN")).upper(),
        }

    async def _validate_navigation_exchange(
        self, intent_id: UUID, values: dict[str, Any]
    ) -> dict[str, Any]:
        if values.get("section") != "services":
            raise ResourceNotFound("数字人操作意图")
        prefill = values.get("prefill")
        if not isinstance(prefill, dict) or set(prefill) != {"service_id"}:
            raise ResourceNotFound("数字人操作意图")
        try:
            service_id = UUID(str(prefill["service_id"]))
        except (ValueError, TypeError, AttributeError):
            raise ResourceNotFound("数字人操作意图") from None
        resolver = getattr(self.repository, "get_navigation_options", None)
        if not callable(resolver):
            raise ResourceNotFound("事项线下网点")
        try:
            raw = await resolver(service_id)
        except Exception:
            raise ResourceNotFound("事项线下网点") from None
        option = self._normalize_navigation_option(service_id, raw)
        if (
            option is None
            or option["published"] is not True
            or option["has_active_locations"] is not True
        ):
            raise ResourceNotFound("事项线下网点")
        return {
            "intent_id": intent_id,
            "type": self._PUBLIC_NAVIGATION_INTENT,
            "label": "前往事项服务查看线下网点",
            "section": "services",
            # Re-query locations on the phone and let the user choose. Never
            # exchange a window, address, coordinate, URL or arbitrary command.
            "prefill": {"service_id": str(service_id)},
        }

    async def quota_identity(
        self, client_id: str | None
    ) -> tuple[UUID | None, str | None]:
        principal, session_id, values = await self._client_context(client_id)
        if principal is not None:
            return principal.account_id, None
        if session_id is not None and values is not None:
            quota_key = str(values.get("anonymous_quota_key") or "")
            if len(quota_key) == 64:
                return None, f"metastudio-client:{quota_key}"
        return None, None

    async def _client_context(
        self, client_id: str | None
    ) -> tuple[Principal | None, UUID | None, dict[str, Any] | None]:
        if not client_id:
            return None, None, None
        try:
            session_id = UUID(client_id)
        except ValueError:
            return None, None, None
        try:
            values = await self.sessions.get(session_id)
        except Exception as exc:
            raise DependencyUnavailable("metastudio_session") from exc
        if not values:
            return None, None, None
        try:
            # Retain a rolling-deploy fallback for already-issued legacy
            # sessions. New sessions only persist the longer context expiry.
            raw_context_expiry = values.get("context_expires_at", values.get("expires_at"))
            context_expires_at = datetime.fromisoformat(str(raw_context_expiry))
            if context_expires_at.tzinfo is None:
                context_expires_at = context_expires_at.replace(tzinfo=timezone.utc)
            if context_expires_at <= datetime.now(timezone.utc):
                return None, None, None
            account_id_value = values.get("account_id")
            role_value = values.get("role")
            if account_id_value is None and role_value is None:
                if not self._valid_anonymous_values(values):
                    return None, None, None
                return None, session_id, values
            if not account_id_value or not role_value:
                return None, None, None
            account_id = UUID(str(account_id_value))
            account = await self.repository.get_account_record(account_id)
            if (
                account is None
                or not account.active
                or account.token_version != int(values.get("token_version") or 0)
                or account.role != str(values["role"])
            ):
                return None, None, None
            principal = Principal(
                account_id=account_id,
                username=account.username,
                display_name=account.display_name,
                role=Role(account.role),
                applicant_type=(
                    ApplicantType(str(account.applicant_type))
                    if account.applicant_type
                    else None
                ),
                token_version=account.token_version,
                department_id=account.department_id,
            )
        except (ValueError, TypeError, KeyError):
            return None, None, None
        return principal, session_id, values

    @staticmethod
    def _valid_anonymous_values(values: dict[str, Any]) -> bool:
        quota_key = str(values.get("anonymous_quota_key") or "")
        return (
            values.get("account_id") is None
            and values.get("role") is None
            and len(quota_key) == 64
            and all(character in "0123456789abcdef" for character in quota_key)
        )

    def _valid_server_address(self) -> bool:
        return self._server_address == (
            "metastudio-api.cn-north-4.myhuaweicloud.com"
        )
