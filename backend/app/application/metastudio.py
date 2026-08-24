from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.application.coordinators import ConsultationCoordinator
from app.application.dtos import ChatCommand, ChatResult, Principal
from app.application.ports import (
    BusinessRepositoryPort,
    MetaStudioOnceCodePort,
    MetaStudioSessionPort,
)
from app.domain.enums import ApplicantType, Role
from app.domain.policies import DigitalHumanIntentPolicy
from app.errors import DependencyUnavailable, ResourceNotFound


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

        result = await self.consultations.chat(
            ChatCommand(
                message=current_question,
                session_id=internal_session_id,
                conversation_history=safe_messages[:-1],
            ),
            principal,
            on_delta=bounded_delta if on_delta is not None else None,
        )
        content = result.answer[:4096]
        proposal = self._intent_policy.propose(
            current_question,
            principal.role if principal else None,
            result.suggested_actions,
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

    async def exchange_intent(
        self,
        principal: Principal,
        intent_id: UUID,
        client_session_id: UUID,
        chat_id: str,
    ) -> dict[str, Any]:
        session_principal, live_session_id, _ = await self._client_context(
            str(client_session_id)
        )
        if (
            session_principal is None
            or live_session_id != client_session_id
            or session_principal.account_id != principal.account_id
            or session_principal.role != principal.role
        ):
            # Conceal whether either the intent or a stale/cross-account
            # client session exists. A live authenticated session is mandatory.
            raise ResourceNotFound("数字人操作意图")
        try:
            values = await self.repository.consume_digital_human_intent(
                intent_id,
                principal.account_id,
                principal.role,
                client_session_id,
                self._opaque_hash("client-chat", chat_id),
                datetime.now(timezone.utc),
            )
        except ResourceNotFound:
            raise
        return {**values, "requires_confirmation": True}

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
            if not values.get("account_id") or not values.get("role"):
                return None, session_id, values
            account_id = UUID(str(values["account_id"]))
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

    def _valid_server_address(self) -> bool:
        return self._server_address == (
            "metastudio-api.cn-north-4.myhuaweicloud.com"
        )
