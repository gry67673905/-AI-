from __future__ import annotations

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.application.dtos import ChatResult, Principal, VisualContextData
from app.application.metastudio import (
    MetaStudioAnswer,
    MetaStudioChatCommand,
    MetaStudioCoordinator,
    MetaStudioTurn,
)
from app.domain.enums import ApplicantType, Role
from app.domain.policies import DigitalHumanIntentPolicy
from app.errors import (
    AuthenticationRequired,
    ConflictError,
    DependencyUnavailable,
    ResourceNotFound,
)
from app.infrastructure.metastudio import (
    HuaweiMetaStudioOnceCodeAdapter,
    MetaStudioCallbackAuthenticator,
)
from app.infrastructure.records import DigitalHumanActionIntentRecord
from app.infrastructure.repositories import BusinessRepository
from app.main import create_app
from app.schemas import HealthCheck
from app.security import redact_sensitive


class MemorySessionStore:
    def __init__(self) -> None:
        self.values: dict[UUID, dict[str, Any]] = {}
        self.ttls: dict[UUID, int] = {}
        self.replays: set[str] = set()
        self.replay_ttls: list[int] = []

    async def put(self, session_id: UUID, values: dict[str, Any], ttl: int) -> None:
        self.values[session_id] = values
        self.ttls[session_id] = ttl

    async def get(self, session_id: UUID) -> dict[str, Any] | None:
        return self.values.get(session_id)

    async def claim_replay(self, replay_key: str, ttl: int) -> bool:
        self.replay_ttls.append(ttl)
        if replay_key in self.replays:
            return False
        self.replays.add(replay_key)
        return True


@pytest.mark.asyncio
async def test_callback_hmac_uses_full_url_decimal_millis_and_rejects_replay() -> None:
    store = MemorySessionStore()
    callback_url = "https://example.test/api/v1/integrations/metastudio/llm"
    app_id = "0123456789abcdef0123456789abcdef"
    app_key = "abcdef0123456789abcdef0123456789"
    timestamp_ms = 1_774_400_000_123
    time_stamp = format(timestamp_ms, "x")
    signature = hmac.new(
        app_key.encode(),
        f"{callback_url}{timestamp_ms}".encode(),
        hashlib.sha256,
    ).hexdigest()
    auth = MetaStudioCallbackAuthenticator(
        enabled=True,
        app_id=app_id,
        app_key=app_key,
        callback_url=callback_url,
        replay_window_seconds=300,
        sessions=store,
    )

    assert await auth.verify(signature, time_stamp, app_id, now_ms=timestamp_ms)
    assert not await auth.verify(signature, time_stamp, app_id, now_ms=timestamp_ms)
    assert not await auth.verify(signature, "0" + time_stamp, app_id, now_ms=timestamp_ms)
    assert not await auth.verify("0" * 64, format(timestamp_ms + 1, "x"), app_id, now_ms=timestamp_ms)
    assert not await auth.verify(signature, time_stamp, "other", now_ms=timestamp_ms)
    assert not await auth.verify(signature, time_stamp, "政务" * 16, now_ms=timestamp_ms)


@pytest.mark.asyncio
async def test_future_callback_replay_claim_outlives_full_acceptance_window() -> None:
    store = MemorySessionStore()
    callback_url = "https://example.test/api/v1/integrations/metastudio/llm"
    app_id = "0123456789abcdef0123456789abcdef"
    app_key = "abcdef0123456789abcdef0123456789"
    now_ms = 1_774_400_000_000
    timestamp_ms = now_ms + 299_000
    signature = hmac.new(
        app_key.encode(), f"{callback_url}{timestamp_ms}".encode(), hashlib.sha256
    ).hexdigest()
    auth = MetaStudioCallbackAuthenticator(
        enabled=True,
        app_id=app_id,
        app_key=app_key,
        callback_url=callback_url,
        replay_window_seconds=300,
        sessions=store,
    )

    assert await auth.verify(signature, format(timestamp_ms, "x"), app_id, now_ms=now_ms)
    assert store.replay_ttls[-1] >= 599


@pytest.mark.asyncio
@pytest.mark.parametrize("offset_ms", [-300_001, 300_001])
async def test_callback_rejects_timestamps_outside_window(offset_ms: int) -> None:
    store = MemorySessionStore()
    callback_url = "https://example.test/api/v1/integrations/metastudio/llm"
    app_id = "a" * 32
    app_key = "b" * 32
    now_ms = 1_700_000_000_000
    timestamp_ms = now_ms + offset_ms
    signature = hmac.new(
        app_key.encode(), f"{callback_url}{timestamp_ms}".encode(), hashlib.sha256
    ).hexdigest()
    auth = MetaStudioCallbackAuthenticator(
        enabled=True,
        app_id=app_id,
        app_key=app_key,
        callback_url=callback_url,
        replay_window_seconds=300,
        sessions=store,
    )

    assert not await auth.verify(
        signature, format(timestamp_ms, "x"), app_id, now_ms=now_ms
    )
    assert store.replays == set()


@pytest.mark.asyncio
async def test_once_code_adapter_refuses_missing_credentials_before_http() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"once_code": "should-not-be-used"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HuaweiMetaStudioOnceCodeAdapter(
        enabled=True,
        endpoint="https://metastudio.cn-north-4.myhuaweicloud.com",
        project_id=None,
        access_key=None,
        secret_key=None,
        timeout_seconds=1,
        client=client,
    )
    with pytest.raises(DependencyUnavailable) as raised:
        await adapter.create_once_code("gov_test")
    assert raised.value.status_code == 503
    assert calls == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_once_code_adapter_signs_server_side_and_returns_only_code() -> None:
    captured: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json={"once_code": "once-unit-test"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HuaweiMetaStudioOnceCodeAdapter(
        enabled=True,
        endpoint="https://metastudio.cn-north-4.myhuaweicloud.com",
        project_id="project01",
        access_key="access-key-unit",
        secret_key="secret-key-unit",
        timeout_seconds=1,
        client=client,
    )
    assert await adapter.create_once_code("gov_user") == "once-unit-test"
    assert captured is not None
    assert captured.url.path == "/v1/project01/digital-human-chat/once-code"
    assert captured.headers["authorization"].startswith("SDK-HMAC-SHA256 Access=")
    assert "secret-key-unit" not in captured.headers["authorization"]
    assert captured.headers["x-app-userid"] == "gov_user"
    fixed = adapter._signed_headers(
        str(captured.url), "gov_user", "20260823T010203Z"
    )
    # Fixed vector independently verified against Huawei's official
    # huaweicloudsdkcore Signer 3.1.183.
    assert fixed["Authorization"] == (
        "SDK-HMAC-SHA256 Access=access-key-unit, "
        "SignedHeaders=host;x-app-userid;x-project-id;x-sdk-date, "
        "Signature=0db79c87f1e7b0db65b5878a03f266906b5058c37a68418d9f9675d9726cf314"
    )
    await client.aclose()


class CapturingConsultations:
    def __init__(self) -> None:
        self.security = SimpleNamespace(
            redact_public_text=lambda value: str(redact_sensitive(value))
        )
        self.command = None
        self.principal = None
        self.calls = 0
        self.suggested_actions: list[dict[str, Any]] = []
        self.answer = "演示回答"

    async def chat(self, command, principal, execution_context=None, on_delta=None):
        self.calls += 1
        self.command = command
        self.principal = principal
        if on_delta:
            await on_delta("增量")
        return ChatResult(
            request_id=uuid4(),
            session_id=command.session_id,
            answer=self.answer,
            suggested_actions=self.suggested_actions,
        )


class IntentRepository:
    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None
        self.consumed: dict[str, Any] | None = None
        self.account: Any | None = None
        self.navigation_options: dict[str, Any] | None = None
        self.consume_result: dict[str, Any] | None = None

    async def get_account_record(self, _account_id: UUID):
        return self.account

    async def create_digital_human_intent(self, *args):
        self.created = {
            "owner": args[0],
            "role": args[1],
            "session": args[2],
            "chat_hash": args[3],
            "type": args[4],
            "label": args[5],
            "section": args[6],
            "prefill": args[7],
            "expires_at": args[8],
        }
        return {"id": uuid4(), **{key: self.created[key] for key in ("type", "label", "section", "prefill", "expires_at")}}

    async def get_navigation_options(self, service_id: UUID):
        if self.navigation_options is None:
            raise ResourceNotFound("事项线下网点")
        assert self.navigation_options["service"]["id"] == str(service_id)
        return self.navigation_options

    async def consume_digital_human_intent(self, *args, **kwargs):
        self.consumed = {"args": args, "kwargs": kwargs}
        if self.consume_result is not None:
            return {"intent_id": args[0], **self.consume_result}
        return {
            "intent_id": args[0],
            "type": "NAVIGATE",
            "label": "确认预约",
            "section": "applications",
            "prefill": {},
        }


class FakeOnceCodes:
    def __init__(self) -> None:
        self.calls = 0

    async def create_once_code(self, _app_user_id: str) -> str:
        self.calls += 1
        return "once-code"


@pytest.mark.asyncio
async def test_client_session_returns_launch_bundle_without_persisting_once_code() -> None:
    sessions = MemorySessionStore()
    repository = IntentRepository()
    consultations = CapturingConsultations()
    once_codes = FakeOnceCodes()
    coordinator = MetaStudioCoordinator(
        repository,  # type: ignore[arg-type]
        consultations,  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        once_codes,
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )
    result = await coordinator.create_client_session(None, "203.0.113.10")

    assert result["once_code"] == "once-code"
    assert result["server_address"] == "metastudio-api.cn-north-4.myhuaweicloud.com"
    assert once_codes.calls == 1
    stored = sessions.values[result["session_id"]]
    now = datetime.now(timezone.utc)
    launch_ttl = (result["expires_at"] - now).total_seconds()
    context_ttl = (
        datetime.fromisoformat(stored["context_expires_at"]) - now
    ).total_seconds()
    assert 295 <= launch_ttl <= 300
    assert 1795 <= context_ttl <= 1800
    assert 1795 <= sessions.ttls[result["session_id"]] <= 1800
    assert "expires_at" not in stored
    assert "once_code" not in stored
    assert "access_key" not in stored
    assert "secret_key" not in stored
    assert "203.0.113.10" not in repr(stored)
    assert len(stored["anonymous_quota_key"]) == 64


@pytest.mark.asyncio
async def test_client_context_accepts_live_legacy_expires_at_during_rolling_upgrade() -> None:
    sessions = MemorySessionStore()
    client_session_id = uuid4()
    sessions.values[client_session_id] = {
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=2)
        ).isoformat(),
        "account_id": None,
        "role": None,
        "anonymous_quota_key": "a" * 64,
    }
    coordinator = MetaStudioCoordinator(
        IntentRepository(),  # type: ignore[arg-type]
        CapturingConsultations(),  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )

    account_id, quota_key = await coordinator.quota_identity(str(client_session_id))

    assert account_id is None
    assert quota_key == f"metastudio-client:{'a' * 64}"


@pytest.mark.asyncio
async def test_client_context_rejects_expired_context_expires_at() -> None:
    sessions = MemorySessionStore()
    client_session_id = uuid4()
    sessions.values[client_session_id] = {
        "context_expires_at": (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat(),
        "account_id": None,
        "role": None,
        "anonymous_quota_key": "a" * 64,
    }
    coordinator = MetaStudioCoordinator(
        IntentRepository(),  # type: ignore[arg-type]
        CapturingConsultations(),  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )

    account_id, quota_key = await coordinator.quota_identity(str(client_session_id))

    assert account_id is None
    assert quota_key is None


@pytest.mark.asyncio
async def test_client_session_rejects_scheme_in_sdk_server_before_once_code_call() -> None:
    once_codes = FakeOnceCodes()
    coordinator = MetaStudioCoordinator(
        IntentRepository(),  # type: ignore[arg-type]
        CapturingConsultations(),  # type: ignore[arg-type]
        MemorySessionStore(),  # type: ignore[arg-type]
        once_codes,
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="https://metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )
    with pytest.raises(DependencyUnavailable):
        await coordinator.create_client_session(None, "203.0.113.10")
    assert once_codes.calls == 0


@pytest.mark.asyncio
async def test_anonymous_session_only_receives_safe_navigation_intent() -> None:
    sessions = MemorySessionStore()
    client_session_id = uuid4()
    sessions.values[client_session_id] = {
        "context_expires_at": "2099-01-01T00:00:00+00:00",
        "account_id": None,
        "role": None,
        "anonymous_quota_key": "a" * 64,
    }
    repository = IntentRepository()
    coordinator = MetaStudioCoordinator(
        repository,  # type: ignore[arg-type]
        CapturingConsultations(),  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )
    answer = await coordinator.answer(
        MetaStudioChatCommand(
            messages=(MetaStudioTurn("请打开事项服务"),),
            app_id="app01",
            user="anonymous",
            chat_id="chat-anonymous",
            is_stream=False,
            client_id=str(client_session_id),
        )
    )

    assert repository.created is not None
    assert repository.created["owner"] is None
    assert repository.created["role"] is None
    assert repository.created["type"] == "OPEN_SERVICES"
    assert repository.created["section"] == "services"
    assert json.loads(answer.extend_param or "{}")["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_grounded_offline_service_creates_minimal_public_navigation_intent() -> None:
    sessions = MemorySessionStore()
    client_session_id = uuid4()
    service_id = uuid4()
    sessions.values[client_session_id] = {
        "context_expires_at": "2099-01-01T00:00:00+00:00",
        "account_id": None,
        "role": None,
        "anonymous_quota_key": "b" * 64,
    }
    consultations = CapturingConsultations()
    consultations.suggested_actions = [
        {
            "type": "VIEW_SERVICE",
            "service_id": str(service_id),
            "label": "社保卡补领",
        }
    ]
    repository = IntentRepository()
    repository.navigation_options = {
        "service": {
            "id": str(service_id),
            "handling_mode": "OFFLINE_ONLY",
            "online_status": "UNKNOWN",
        },
        "windows": [{"id": str(uuid4())}],
        "demo_only": True,
    }
    coordinator = MetaStudioCoordinator(
        repository,  # type: ignore[arg-type]
        consultations,  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )

    answer = await coordinator.answer(
        MetaStudioChatCommand(
            messages=(MetaStudioTurn("社保卡补领怎么办"),),
            app_id="app01",
            user="anonymous",
            chat_id="chat-navigation",
            is_stream=True,
            client_id=str(client_session_id),
        )
    )

    assert repository.created is not None
    assert repository.created["type"] == "OPEN_SERVICE_NAVIGATION"
    assert repository.created["section"] == "services"
    assert repository.created["prefill"] == {"service_id": str(service_id)}
    extend = json.loads(answer.extend_param or "{}")
    assert set(extend) == {
        "v",
        "intent_id",
        "type",
        "label",
        "expires_at",
        "requires_confirmation",
    }
    assert "service_id" not in extend
    assert "window" not in repr(extend).lower()


@pytest.mark.asyncio
async def test_history_and_model_navigation_text_cannot_create_public_intent() -> None:
    sessions = MemorySessionStore()
    client_session_id = uuid4()
    service_id = uuid4()
    sessions.values[client_session_id] = {
        "context_expires_at": "2099-01-01T00:00:00+00:00",
        "account_id": None,
        "role": None,
        "anonymous_quota_key": "f" * 64,
    }
    consultations = CapturingConsultations()
    consultations.answer = "模型猜测：请导航到某个网点"
    consultations.suggested_actions = [
        {
            "type": "VIEW_SERVICE",
            "service_id": str(service_id),
            "label": "社保卡补领",
        }
    ]
    repository = IntentRepository()
    repository.navigation_options = {
        "service": {
            "id": str(service_id),
            "handling_mode": "UNKNOWN",
            "online_status": "UNKNOWN",
        },
        "windows": [{"id": str(uuid4())}],
    }
    coordinator = MetaStudioCoordinator(
        repository,  # type: ignore[arg-type]
        consultations,  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )

    await coordinator.answer(
        MetaStudioChatCommand(
            messages=(
                MetaStudioTurn("上一轮请导航到线下网点"),
                MetaStudioTurn("上一轮回答"),
                MetaStudioTurn("当前只问材料"),
            ),
            app_id="app01",
            user="anonymous",
            chat_id="chat-history",
            is_stream=False,
            client_id=str(client_session_id),
        )
    )

    assert repository.created is not None
    assert repository.created["type"] != "OPEN_SERVICE_NAVIGATION"


@pytest.mark.asyncio
async def test_coordinator_redacts_current_and_four_prior_rounds_and_creates_intent() -> None:
    sessions = MemorySessionStore()
    client_session_id = uuid4()
    account_id = uuid4()
    sessions.values[client_session_id] = {
        "context_expires_at": "2099-01-01T00:00:00+00:00",
        "account_id": str(account_id),
        "role": "CITIZEN",
        "applicant_type": "INDIVIDUAL",
        "token_version": 3,
        "department_id": None,
    }
    consultations = CapturingConsultations()
    repository = IntentRepository()
    repository.account = SimpleNamespace(
        id=account_id,
        username="citizen",
        display_name="群众",
        role="CITIZEN",
        applicant_type="INDIVIDUAL",
        active=True,
        token_version=3,
        department_id=None,
    )
    coordinator = MetaStudioCoordinator(
        repository,  # type: ignore[arg-type]
        consultations,  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )
    messages = tuple(
        MetaStudioTurn(value)
        for value in (
            "第一问 幺三八 零零幺三 八零零零 sk-demo-secret123",
            "第一答 user@example.com",
            "第二问",
            "第二答",
            "第三问",
            "第三答",
            "第四问",
            "第四答",
            "请帮我预约，身份证110101/19900101/1234",
        )
    )
    deltas: list[str] = []

    async def capture_delta(value: str) -> None:
        deltas.append(value)

    answer = await coordinator.answer(
        MetaStudioChatCommand(
            messages=messages,
            app_id="app01",
            user="raw-user-is-ignored",
            chat_id="chat-01",
            is_stream=True,
            client_id=str(client_session_id),
        ),
        on_delta=capture_delta,
    )

    assert consultations.command.message.endswith("[REDACTED_ID]")
    assert len(consultations.command.conversation_history) == 8
    assert [
        item.role for item in consultations.command.conversation_history
    ] == ["human", "ai", "human", "ai", "human", "ai", "human", "ai"]
    assert consultations.command.conversation_history[-1].content == "第四答"
    assert "幺三八 零零幺三 八零零零" not in repr(consultations.command)
    assert "110101/19900101/1234" not in repr(consultations.command)
    assert "sk-demo-secret123" not in repr(consultations.command)
    assert "user@example.com" not in repr(consultations.command)
    assert consultations.principal.account_id == account_id
    assert deltas == ["增量"]
    assert repository.created is not None
    assert repository.created["section"] == "applications"
    assert json.loads(answer.extend_param or "{}")["requires_confirmation"] is True
    assert len(str(answer.created)) == 14


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["unavailable", "exception"])
async def test_visual_failure_continues_one_normal_streamed_answer(
    failure_mode: str,
) -> None:
    sessions = MemorySessionStore()
    client_session_id = uuid4()
    account_id = uuid4()
    sessions.values[client_session_id] = {
        "context_expires_at": "2099-01-01T00:00:00+00:00",
        "account_id": str(account_id),
        "role": "CITIZEN",
        "applicant_type": "INDIVIDUAL",
        "token_version": 3,
        "department_id": None,
    }
    consultations = CapturingConsultations()
    repository = IntentRepository()
    repository.account = SimpleNamespace(
        id=account_id,
        username="citizen",
        display_name="群众",
        role="CITIZEN",
        applicant_type="INDIVIDUAL",
        active=True,
        token_version=3,
        department_id=None,
    )

    class FailingVision:
        def __init__(self) -> None:
            self.calls = 0

        async def analyze_latest_turn(
            self, received_session_id: UUID, _question: str
        ) -> VisualContextData:
            self.calls += 1
            assert received_session_id == client_session_id
            if failure_mode == "exception":
                raise RuntimeError("vision provider failed")
            return VisualContextData(
                client_session_id=client_session_id,
                turn_sequence=1,
                frame_count=1,
                scene="",
                available=False,
            )

    vision = FailingVision()
    coordinator = MetaStudioCoordinator(
        repository,  # type: ignore[arg-type]
        consultations,  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
        vision=vision,  # type: ignore[arg-type]
    )
    deltas: list[str] = []

    async def capture_delta(value: str) -> None:
        deltas.append(value)

    answer = await coordinator.answer(
        MetaStudioChatCommand(
            messages=(MetaStudioTurn("这个怎么办？"),),
            app_id="app01",
            user="ignored-provider-user",
            chat_id="chat-visual-failure",
            is_stream=True,
            client_id=str(client_session_id),
        ),
        on_delta=capture_delta,
    )

    assert vision.calls == 1
    assert consultations.calls == 1
    assert consultations.command.visual_context is None
    assert answer.content == "演示回答"
    assert deltas == ["增量"]
    assert answer.chat_result.warnings == [
        "visual_unavailable: 本轮视觉信息不可用，已继续处理用户问题"
    ]


@pytest.mark.asyncio
async def test_exchange_requires_live_matching_client_session() -> None:
    sessions = MemorySessionStore()
    session_id = uuid4()
    account_id = uuid4()
    live_values = {
        "context_expires_at": "2099-01-01T00:00:00+00:00",
        "account_id": str(account_id),
        "role": "CITIZEN",
        "applicant_type": "INDIVIDUAL",
        "token_version": 2,
        "department_id": None,
        "anonymous_quota_key": "a" * 64,
    }
    sessions.values[session_id] = live_values
    repository = IntentRepository()
    repository.account = SimpleNamespace(
        id=account_id,
        username="citizen",
        display_name="群众",
        role="CITIZEN",
        applicant_type="INDIVIDUAL",
        active=True,
        token_version=2,
        department_id=None,
    )
    coordinator = MetaStudioCoordinator(
        repository,  # type: ignore[arg-type]
        CapturingConsultations(),  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )
    principal = Principal(
        account_id=account_id,
        username="citizen",
        display_name="群众",
        role=Role.CITIZEN,
        applicant_type=ApplicantType.INDIVIDUAL,
        token_version=2,
    )

    result = await coordinator.exchange_intent(
        principal, uuid4(), session_id, "semantic-turn-01"
    )
    assert result["requires_confirmation"] is True
    assert repository.consumed is not None

    sessions.values.pop(session_id)
    with pytest.raises(ResourceNotFound):
        await coordinator.exchange_intent(
            principal, uuid4(), session_id, "semantic-turn-02"
        )

    sessions.values[session_id] = live_values
    repository.account.active = False
    with pytest.raises(ResourceNotFound):
        await coordinator.exchange_intent(
            principal, uuid4(), session_id, "semantic-turn-frozen-account"
        )


@pytest.mark.asyncio
async def test_anonymous_exchange_allows_only_fresh_grounded_public_navigation() -> None:
    sessions = MemorySessionStore()
    session_id = uuid4()
    service_id = uuid4()
    sessions.values[session_id] = {
        "context_expires_at": "2099-01-01T00:00:00+00:00",
        "account_id": None,
        "role": None,
        "anonymous_quota_key": "c" * 64,
    }
    repository = IntentRepository()
    repository.consume_result = {
        "type": "OPEN_SERVICE_NAVIGATION",
        "label": "untrusted stored label",
        "section": "services",
        "prefill": {"service_id": str(service_id)},
    }
    repository.navigation_options = {
        "service": {
            "id": str(service_id),
            "handling_mode": "BOTH",
            "online_status": "AVAILABLE",
        },
        "windows": [{"id": str(uuid4())}],
        "demo_only": True,
    }
    coordinator = MetaStudioCoordinator(
        repository,  # type: ignore[arg-type]
        CapturingConsultations(),  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )
    intent_id = uuid4()

    result = await coordinator.exchange_intent(
        None, intent_id, session_id, "anonymous-semantic-turn"
    )

    assert result == {
        "intent_id": intent_id,
        "type": "OPEN_SERVICE_NAVIGATION",
        "label": "前往事项服务查看线下网点",
        "section": "services",
        "prefill": {"service_id": str(service_id)},
        "requires_confirmation": True,
    }
    assert repository.consumed is not None
    consumed_args = repository.consumed["args"]
    assert consumed_args[1] is None
    assert consumed_args[2] is None
    assert repository.consumed["kwargs"] == {
        "required_intent_type": "OPEN_SERVICE_NAVIGATION"
    }

    repository.consume_result = {
        "type": "OPEN_SERVICES",
        "label": "前往事项服务",
        "section": "services",
        "prefill": {},
    }
    with pytest.raises(AuthenticationRequired):
        await coordinator.exchange_intent(
            None, uuid4(), session_id, "anonymous-generic-intent"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, Role.CITIZEN, Role.STAFF, Role.ADMIN])
async def test_grounded_public_navigation_exchange_is_available_to_every_role(
    role: Role | None,
) -> None:
    sessions = MemorySessionStore()
    session_id = uuid4()
    service_id = uuid4()
    account_id = uuid4() if role is not None else None
    sessions.values[session_id] = {
        "context_expires_at": "2099-01-01T00:00:00+00:00",
        "account_id": str(account_id) if account_id is not None else None,
        "role": role.value if role is not None else None,
        "applicant_type": (
            "INDIVIDUAL" if role is Role.CITIZEN else None
        ),
        "token_version": 4 if role is not None else None,
        "department_id": None,
        "anonymous_quota_key": "e" * 64,
    }
    repository = IntentRepository()
    if role is not None:
        repository.account = SimpleNamespace(
            id=account_id,
            username=f"{role.value.lower()}-user",
            display_name="演示用户",
            role=role.value,
            applicant_type=("INDIVIDUAL" if role is Role.CITIZEN else None),
            active=True,
            token_version=4,
            department_id=None,
        )
    repository.consume_result = {
        "type": "OPEN_SERVICE_NAVIGATION",
        "label": "前往事项服务查看线下网点",
        "section": "services",
        "prefill": {"service_id": str(service_id)},
    }
    repository.navigation_options = {
        "service": {
            "id": str(service_id),
            "handling_mode": "UNKNOWN",
            "online_status": "UNKNOWN",
        },
        "windows": [{"id": str(uuid4())}],
    }
    coordinator = MetaStudioCoordinator(
        repository,  # type: ignore[arg-type]
        CapturingConsultations(),  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )
    principal = (
        Principal(
            account_id=account_id,
            username=f"{role.value.lower()}-user",
            display_name="演示用户",
            role=role,
            applicant_type=(
                ApplicantType.INDIVIDUAL if role is Role.CITIZEN else None
            ),
            token_version=4,
        )
        if role is not None and account_id is not None
        else None
    )

    result = await coordinator.exchange_intent(
        principal, uuid4(), session_id, "public-navigation"
    )

    assert result["type"] == "OPEN_SERVICE_NAVIGATION"
    assert result["prefill"] == {"service_id": str(service_id)}
    assert repository.consumed is not None
    assert repository.consumed["kwargs"]["required_intent_type"] == (
        "OPEN_SERVICE_NAVIGATION" if role is None else None
    )


@pytest.mark.asyncio
async def test_anonymous_navigation_exchange_rejects_unsafe_prefill_and_stale_session() -> None:
    sessions = MemorySessionStore()
    session_id = uuid4()
    service_id = uuid4()
    sessions.values[session_id] = {
        "context_expires_at": "2099-01-01T00:00:00+00:00",
        "account_id": None,
        "role": None,
        "anonymous_quota_key": "d" * 64,
    }
    repository = IntentRepository()
    repository.consume_result = {
        "type": "OPEN_SERVICE_NAVIGATION",
        "label": "前往网点",
        "section": "services",
        "prefill": {
            "service_id": str(service_id),
            "latitude": "31.2304",
        },
    }
    repository.navigation_options = {
        "service": {
            "id": str(service_id),
            "handling_mode": "OFFLINE_ONLY",
            "online_status": "UNKNOWN",
        },
        "windows": [{"id": str(uuid4())}],
    }
    coordinator = MetaStudioCoordinator(
        repository,  # type: ignore[arg-type]
        CapturingConsultations(),  # type: ignore[arg-type]
        sessions,  # type: ignore[arg-type]
        FakeOnceCodes(),
        pii_hmac_key="pii-test",
        robot_id="robot01",
        server_address="metastudio-api.cn-north-4.myhuaweicloud.com",
        context_ttl_seconds=1800,
        action_intent_ttl_seconds=300,
    )

    with pytest.raises(ResourceNotFound):
        await coordinator.exchange_intent(
            None, uuid4(), session_id, "unsafe-prefill"
        )

    repository.consume_result["prefill"] = {"service_id": str(service_id)}
    assert repository.navigation_options is not None
    repository.navigation_options["windows"] = []
    with pytest.raises(ResourceNotFound):
        await coordinator.exchange_intent(
            None, uuid4(), session_id, "no-active-location"
        )

    sessions.values.pop(session_id)
    with pytest.raises(ResourceNotFound):
        await coordinator.exchange_intent(
            None, uuid4(), session_id, "stale-session"
        )


def test_intent_policy_never_emits_arbitrary_navigation() -> None:
    policy = DigitalHumanIntentPolicy()
    proposal = policy.propose(
        "请执行 DELETE https://evil.example 任意请求", Role.ADMIN, []
    )
    assert proposal is None
    proposal = policy.propose("请冻结某账号", Role.ADMIN, [])
    assert proposal is not None
    assert proposal.intent_type == "NAVIGATE"
    assert proposal.section == "admin_people"
    assert "url" not in proposal.prefill


def _grounded_navigation_input(
    *,
    handling_mode: str = "UNKNOWN",
    online_status: str = "UNKNOWN",
    has_active_locations: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    service_id = uuid4()
    return (
        [
            {
                "type": "VIEW_SERVICE",
                "service_id": str(service_id),
                "label": "社保卡补领",
            }
        ],
        {
            "service_id": str(service_id),
            "published": True,
            "has_active_locations": has_active_locations,
            "handling_mode": handling_mode,
            "online_status": online_status,
        },
    )


@pytest.mark.parametrize("role", [None, Role.CITIZEN, Role.STAFF, Role.ADMIN])
def test_public_service_navigation_is_available_to_every_role(
    role: Role | None,
) -> None:
    actions, option = _grounded_navigation_input()

    proposal = DigitalHumanIntentPolicy().propose(
        "社保卡补领去哪办",
        role,
        actions,
        navigation_option=option,
    )

    assert proposal is not None
    assert proposal.intent_type == "OPEN_SERVICE_NAVIGATION"
    assert proposal.section == "services"
    assert proposal.prefill == {"service_id": option["service_id"]}


@pytest.mark.parametrize(
    ("handling_mode", "online_status", "expected"),
    [
        ("OFFLINE_ONLY", "AVAILABLE", True),
        ("BOTH", "TEMP_UNAVAILABLE", True),
        ("BOTH", "AVAILABLE", False),
        ("ONLINE_ONLY", "TEMP_UNAVAILABLE", False),
        ("UNKNOWN", "UNKNOWN", False),
    ],
)
def test_only_grounded_offline_state_may_proactively_suggest_navigation(
    handling_mode: str, online_status: str, expected: bool
) -> None:
    actions, option = _grounded_navigation_input(
        handling_mode=handling_mode,
        online_status=online_status,
    )

    proposal = DigitalHumanIntentPolicy().propose(
        "社保卡补领怎么办",
        None,
        actions,
        navigation_option=option,
    )

    assert (proposal is not None and proposal.intent_type == "OPEN_SERVICE_NAVIGATION") is expected


@pytest.mark.parametrize(
    "utterance",
    [
        "社保卡补领办理流程怎么走",
        "导航到坐标31.2304,121.4737",
        "请按经纬度导航办理社保卡",
        "导航到https://evil.example",
        "不要导航，我只想了解社保卡材料",
    ],
)
def test_navigation_rejects_process_homonyms_coordinates_and_external_targets(
    utterance: str,
) -> None:
    actions, option = _grounded_navigation_input(handling_mode="OFFLINE_ONLY")

    proposal = DigitalHumanIntentPolicy().propose(
        utterance,
        None,
        actions,
        navigation_option=option,
    )

    assert proposal is None or proposal.intent_type != "OPEN_SERVICE_NAVIGATION"


def test_navigation_requires_one_published_service_with_an_active_location() -> None:
    actions, option = _grounded_navigation_input(has_active_locations=False)
    policy = DigitalHumanIntentPolicy()

    proposal = policy.propose(
        "社保卡去哪办", None, actions, navigation_option=option
    )
    assert proposal is None or proposal.intent_type != "OPEN_SERVICE_NAVIGATION"
    option["has_active_locations"] = True
    option["published"] = False
    proposal = policy.propose(
        "社保卡去哪办", None, actions, navigation_option=option
    )
    assert proposal is None or proposal.intent_type != "OPEN_SERVICE_NAVIGATION"
    option["published"] = True
    mismatched = {**option, "service_id": str(uuid4())}
    proposal = policy.propose(
        "社保卡去哪办", None, actions, navigation_option=mismatched
    )
    assert proposal is None or proposal.intent_type != "OPEN_SERVICE_NAVIGATION"


@pytest.mark.parametrize(
    ("role", "utterance", "section"),
    [
        (Role.CITIZEN, "提交申请", "applications"),
        (Role.CITIZEN, "取消预约", "applications"),
        (Role.CITIZEN, "取消支付", "applications"),
        (Role.CITIZEN, "创建人脸核验", "applications"),
        (Role.CITIZEN, "取消邮寄", "applications"),
        (Role.CITIZEN, "转人工并反馈", "consultation"),
        (Role.STAFF, "认领并审核待办", "staff_tasks"),
        (Role.STAFF, "回复人工咨询工单", "staff_handoffs"),
        (Role.ADMIN, "发布事项新版本", "admin_catalog"),
        (Role.ADMIN, "冻结工作人员账号", "admin_people"),
        (Role.ADMIN, "重试并归档知识索引", "admin_knowledge"),
        (Role.ADMIN, "查看审计日志", "admin_audit"),
        (Role.ADMIN, "查看运营指标", "admin_overview"),
    ],
)
def test_intent_policy_maps_each_role_operation_to_closed_workbench_section(
    role: Role, utterance: str, section: str
) -> None:
    proposal = DigitalHumanIntentPolicy().propose(utterance, role, [])
    assert proposal is not None
    assert proposal.intent_type == "NAVIGATE"
    assert proposal.section == section
    assert proposal.prefill == {}


@pytest.mark.parametrize("utterance", ["提交申请", "冻结账号", "审核通过", "归档知识"])
def test_anonymous_mutation_intent_is_login_only(utterance: str) -> None:
    proposal = DigitalHumanIntentPolicy().propose(utterance, None, [])
    assert proposal is not None
    assert proposal.intent_type == "AUTH_REQUIRED"
    assert proposal.section == "login"


class BoundaryAuthenticator:
    def __init__(self, accepted: bool) -> None:
        self.accepted = accepted

    async def verify(self, *_args) -> bool:
        return self.accepted


class BoundaryMetaStudio:
    def __init__(self) -> None:
        self.calls = 0
        self.last_command = None
        self.allow_anonymous_navigation = False
        self.public_service_id = uuid4()

    async def answer(self, command, on_delta=None) -> MetaStudioAnswer:
        self.calls += 1
        self.last_command = command
        if on_delta:
            await on_delta("演示")
            await on_delta("回答")
        result = ChatResult(
            request_id=uuid4(), session_id=uuid4(), answer="演示回答"
        )
        return MetaStudioAnswer(
            response_id="response01",
            created=20_260_823_010_203,
            content="演示回答",
            extend_param='{"v":1,"intent_id":"intent01"}',
            chat_result=result,
        )

    async def quota_identity(self, _client_id):
        return None, "metastudio-client:test"

    async def create_client_session(self, _principal, origin_ip) -> dict[str, Any]:
        self.calls += 1
        return {
            "session_id": uuid4(),
            "once_code": "once-code-value",
            "robot_id": "robot01",
            "server_address": "metastudio-api.cn-north-4.myhuaweicloud.com",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "origin_seen": origin_ip,
        }

    async def exchange_intent(
        self, _principal, intent_id, _session_id, _chat_id
    ) -> dict[str, Any]:
        if _principal is None:
            if not self.allow_anonymous_navigation:
                raise AuthenticationRequired("请先登录后继续")
            return {
                "intent_id": intent_id,
                "type": "OPEN_SERVICE_NAVIGATION",
                "label": "前往事项服务查看线下网点",
                "section": "services",
                "prefill": {"service_id": str(self.public_service_id)},
                "requires_confirmation": True,
            }
        return {
            "intent_id": intent_id,
            "type": "NAVIGATE",
            "label": "前往办件确认",
            "section": "applications",
            "prefill": {},
            "requires_confirmation": True,
        }


class BoundaryAuth:
    async def authenticate(self, _token: str) -> Principal:
        return Principal(
            account_id=uuid4(),
            username="citizen",
            display_name="群众",
            role=Role.CITIZEN,
            applicant_type=ApplicantType.INDIVIDUAL,
            token_version=0,
        )


class BoundaryServices:
    def __init__(self, accepted: bool = True) -> None:
        self.meta = BoundaryMetaStudio()
        self.business = SimpleNamespace(
            metastudio=self.meta,
            metastudio_authenticator=BoundaryAuthenticator(accepted),
            auth=BoundaryAuth(),
        )
        self.chat_quota = None
        self.metastudio_session_quota = None

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def readiness(self) -> dict[str, HealthCheck]:
        return {}


def llm_body(is_stream: bool) -> dict[str, Any]:
    return {
        "messages": [{"content": "社保卡怎么办"}],
        "app_id": "app01",
        "user": "user01",
        "session_id": "chat01",
        "is_stream": is_stream,
    }


def test_callback_nonstream_and_stream_match_metastudio_wire_contract() -> None:
    services = BoundaryServices()
    with TestClient(create_app(services)) as client:
        nonstream = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            json=llm_body(False),
        )
        stream = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            json=llm_body(True),
        )

    assert nonstream.status_code == 200
    assert nonstream.headers["content-type"].startswith(
        "application/json;charset=UTF-8"
    )
    assert nonstream.headers["content-type"].lower().count("charset=") == 1
    assert nonstream.json() == {
        "id": "response01",
        "created": 20_260_823_010_203,
        "choices": [
            {
                "index": 0,
                "message": {
                    "content": "演示回答",
                    "extend_param": '{"v":1,"intent_id":"intent01"}',
                },
            }
        ],
    }
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith(
        "text/event-stream;charset=UTF-8"
    )
    assert stream.headers["content-type"].lower().count("charset=") == 1
    frames = [item for item in stream.text.split("\n\n") if item]
    assert frames[-1] == "data:[DONE]"
    assert all(item.startswith("data:") for item in frames)
    assert '"content":"演示"' in frames[0]
    assert '"content":"回答"' in frames[1]
    assert '"extend_param":"{\\"v\\":1' in frames[1]
    first_stream_payload = json.loads(frames[0].removeprefix("data:"))
    assert len(str(first_stream_payload["created"])) == 13


def test_callback_auth_and_schema_fail_before_consultation() -> None:
    services = BoundaryServices(accepted=False)
    with TestClient(create_app(services)) as client:
        forged = client.post(
            "/api/v1/integrations/metastudio/llm?secret=forged&time_stamp=1",
            json=llm_body(False),
        )
        invalid = client.post(
            "/api/v1/integrations/metastudio/llm?secret=forged&time_stamp=1",
            json={"messages": []},
        )
        blank_message = client.post(
            "/api/v1/integrations/metastudio/llm?secret=forged&time_stamp=1",
            json={
                **llm_body(False),
                "messages": [{"content": "   "}],
            },
        )

    assert forged.status_code == 400
    assert forged.json()["error_code"] == "METASTUDIO.AUTH_FAILED"
    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "METASTUDIO.INVALID_REQUEST"
    assert blank_message.status_code == 400
    assert blank_message.json()["error_code"] == "METASTUDIO.INVALID_REQUEST"
    assert services.meta.calls == 0


def test_callback_accepts_vendor_additions_even_messages_and_string_extend_param() -> None:
    services = BoundaryServices()
    body = {
        **llm_body(False),
        "messages": [
            {"content": "第一问", "role": "user"},
            {"content": "当前问题", "role": "assistant", "vendor_meta": 1},
        ],
        "extend_param": json.dumps(
            {
                "client_id": "opaque-client-id",
                "city": "北京市",
                "vendor_extension": {"ignored": True},
            },
            ensure_ascii=False,
        ),
        "vendor_top_level": {"version": 2},
    }
    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            json=body,
        )

    assert response.status_code == 200
    assert services.meta.calls == 1
    assert services.meta.last_command is not None
    assert len(services.meta.last_command.messages) == 2
    assert services.meta.last_command.messages[-1].content == "当前问题"
    assert services.meta.last_command.client_id == "opaque-client-id"


def test_callback_accepts_empty_string_extend_param_as_absent() -> None:
    services = BoundaryServices()
    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            json={**llm_body(False), "extend_param": ""},
        )

    assert response.status_code == 200
    assert services.meta.calls == 1
    assert services.meta.last_command.client_id is None


@pytest.mark.parametrize(
    "extend_param",
    [
        '["not-an-object"]',
        "{malformed-json",
        "x" * 4097,
        42,
        ["not-an-object"],
        '{"client_id":{"$ne":null}}',
    ],
)
def test_callback_rejects_unsafe_string_extend_param_shapes(
    extend_param: object,
) -> None:
    services = BoundaryServices()
    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            json={**llm_body(False), "extend_param": extend_param},
        )

    assert response.status_code == 400
    assert response.json()["error_code"] == "METASTUDIO.INVALID_REQUEST"
    assert services.meta.calls == 0


def test_callback_schema_diagnostic_contains_shape_but_no_values_or_pydantic_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    services = BoundaryServices()
    body_marker = "BODY-CONTENT-MUST-NOT-APPEAR"
    user_marker = "USER-VALUE-MUST-NOT-APPEAR"
    session_marker = "SESSION-VALUE-MUST-NOT-APPEAR"
    query_marker = "QUERY-SECRET-MUST-NOT-APPEAR"
    caplog.set_level(logging.WARNING, logger="app.boundaries.metastudio")

    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/v1/integrations/metastudio/llm"
            f"?secret={query_marker}&time_stamp=1",
            json={
                **llm_body(False),
                "messages": [{"content": body_marker, "role": "user"}],
                "user": user_marker,
                "session_id": session_marker,
                "extend_param": '["array-is-rejected"]',
                "vendor_top_level": True,
            },
        )

    assert response.status_code == 400
    records = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.boundaries.metastudio"
    ]
    assert len(records) == 1
    diagnostic = records[0]
    assert "metastudio_callback_schema_rejected" in diagnostic
    assert '"name":"messages"' in diagnostic
    assert '"name":"role"' in diagnostic
    assert '"name":"vendor_top_level"' in diagnostic
    assert '"type":"array"' in diagnostic
    assert '"loc":["extend_param"]' in diagnostic
    assert body_marker not in diagnostic
    assert user_marker not in diagnostic
    assert session_marker not in diagnostic
    assert query_marker not in diagnostic
    assert '"input"' not in diagnostic


def test_callback_schema_diagnostic_is_silent_for_unauthenticated_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    services = BoundaryServices(accepted=False)
    caplog.set_level(logging.WARNING, logger="app.boundaries.metastudio")

    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/v1/integrations/metastudio/llm"
            "?secret=forged-secret&time_stamp=1",
            json={
                **llm_body(False),
                "extend_param": '["rejected-array"]',
            },
        )

    assert response.status_code == 400
    assert not [
        record
        for record in caplog.records
        if record.name == "app.boundaries.metastudio"
    ]


def test_callback_rejects_ten_messages_and_oversize_body_before_consultation() -> None:
    services = BoundaryServices()
    ten_messages = [{"content": f"第{index}条"} for index in range(10)]
    with TestClient(create_app(services)) as client:
        too_many = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            json={**llm_body(False), "messages": ten_messages},
        )
        oversized = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            content=b"x" * (128 * 1024 + 1),
            headers={"Content-Type": "application/json"},
        )

    assert too_many.status_code == 400
    assert oversized.status_code == 400
    assert services.meta.calls == 0


class FailingStreamMeta(BoundaryMetaStudio):
    async def answer(self, _command, on_delta=None) -> MetaStudioAnswer:
        self.calls += 1
        if on_delta is not None:
            await on_delta("部分回答")
        raise RuntimeError("synthetic stream interruption")


def test_stream_producer_interruption_emits_safe_terminal_protocol() -> None:
    services = BoundaryServices()
    services.meta = FailingStreamMeta()
    services.business.metastudio = services.meta
    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            json=llm_body(True),
        )

    assert response.status_code == 200
    assert "部分回答" in response.text
    assert "智能问答服务暂不可用" in response.text
    assert response.text.rstrip().endswith("data:[DONE]")


class FailingQuota:
    async def consume(self, _account_id, _client_ip) -> None:
        raise DependencyUnavailable("chat_quota")


def test_callback_quota_failure_is_fail_closed_before_model() -> None:
    services = BoundaryServices()
    services.chat_quota = FailingQuota()
    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            json=llm_body(False),
        )

    assert response.status_code == 503
    assert services.meta.calls == 0


class UnboundQuotaMeta(BoundaryMetaStudio):
    async def quota_identity(self, _client_id):
        return None, None


def test_unbound_provider_callbacks_share_one_conservative_quota_bucket() -> None:
    services = BoundaryServices()
    services.meta = UnboundQuotaMeta()
    services.business.metastudio = services.meta
    quota = CapturingQuota()
    services.chat_quota = quota
    first = llm_body(False)
    second = llm_body(False)
    first["user"] = "provider-session-one"
    second["user"] = "provider-session-two"
    with TestClient(create_app(services)) as client:
        first_response = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            json=first,
        )
        second_response = client.post(
            "/api/v1/integrations/metastudio/llm?secret=x&time_stamp=1",
            json=second,
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert quota.calls == [
        (None, "metastudio-provider:unbound"),
        (None, "metastudio-provider:unbound"),
    ]


def test_action_intent_exchange_keeps_login_boundary_except_public_navigation() -> None:
    services = BoundaryServices()
    intent_id = uuid4()
    body = {"session_id": str(uuid4()), "chat_id": "chat01"}
    url = f"/api/v1/integrations/metastudio/action-intents/{intent_id}/exchange"
    with TestClient(create_app(services)) as client:
        anonymous = client.post(url, json=body)
        authenticated = client.post(
            url, json=body, headers={"Authorization": "Bearer access-token"}
        )
        services.meta.allow_anonymous_navigation = True
        public_navigation = client.post(url, json=body)

    assert anonymous.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.json() == {
        "intent_id": str(intent_id),
        "type": "NAVIGATE",
        "label": "前往办件确认",
        "section": "applications",
        "prefill": {},
        "requires_confirmation": True,
    }
    assert public_navigation.status_code == 200
    assert public_navigation.json() == {
        "intent_id": str(intent_id),
        "type": "OPEN_SERVICE_NAVIGATION",
        "label": "前往事项服务查看线下网点",
        "section": "services",
        "prefill": {"service_id": str(services.meta.public_service_id)},
        "requires_confirmation": True,
    }


class CapturingQuota:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID | None, str]] = []

    async def consume(self, account_id: UUID | None, client_ip: str) -> None:
        self.calls.append((account_id, client_ip))


def test_anonymous_client_session_consumes_ip_quota_before_once_code() -> None:
    services = BoundaryServices()
    quota = CapturingQuota()
    services.metastudio_session_quota = quota
    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/v1/integrations/metastudio/client-sessions", json={}
        )

    assert response.status_code == 200
    assert services.meta.calls == 1
    assert len(quota.calls) == 1
    assert quota.calls[0][0] is None
    assert quota.calls[0][1]
    payload = response.json()
    assert "access_key" not in repr(payload)
    assert "secret_key" not in repr(payload)


class IntentSession:
    def __init__(self, record: DigitalHumanActionIntentRecord | None) -> None:
        self.record = record

    async def scalar(self, _statement):
        return self.record


def repository_with_intent(record: DigitalHumanActionIntentRecord):
    repository = BusinessRepository.__new__(BusinessRepository)
    session = IntentSession(record)
    audits: list[dict[str, Any]] = []

    @asynccontextmanager
    async def transaction():
        yield session

    async def audit(
        _session, _actor_id, action, _entity_type, _entity_id, detail
    ) -> None:
        audits.append({"action": action, "detail": detail})

    repository._transaction = transaction  # type: ignore[method-assign]
    repository._audit = audit  # type: ignore[method-assign]
    return repository, audits


def make_intent(
    *,
    owner_id: UUID | None,
    role: Role | None = Role.CITIZEN,
    session_id: UUID | None = None,
    expires_at: datetime | None = None,
) -> DigitalHumanActionIntentRecord:
    return DigitalHumanActionIntentRecord(
        id=uuid4(),
        owner_account_id=owner_id,
        owner_role=role.value if role is not None else None,
        client_session_id=session_id or uuid4(),
        chat_id_hash="provider-conversation-hash",
        intent_type="NAVIGATE",
        label="前往办件确认",
        section="applications",
        prefill_json={"application_id": "demo-reference"},
        status="ACTIVE",
        expires_at=expires_at or datetime.now(timezone.utc) + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_repository_anonymous_type_and_shape_checks_happen_before_consumption() -> None:
    session_id = uuid4()
    now = datetime.now(timezone.utc)
    generic = make_intent(owner_id=None, role=None, session_id=session_id)
    repository, _ = repository_with_intent(generic)

    with pytest.raises(AuthenticationRequired):
        await repository.consume_digital_human_intent(
            generic.id,
            None,
            None,
            session_id,
            "anonymous-turn",
            now,
            required_intent_type="OPEN_SERVICE_NAVIGATION",
        )
    assert generic.status == "ACTIVE"
    assert generic.consumed_at is None

    navigation = make_intent(owner_id=None, role=None, session_id=session_id)
    navigation.intent_type = "OPEN_SERVICE_NAVIGATION"
    navigation.section = "services"
    navigation.prefill_json = {"service_id": str(uuid4()), "latitude": "31.2"}
    repository, _ = repository_with_intent(navigation)

    with pytest.raises(ResourceNotFound):
        await repository.consume_digital_human_intent(
            navigation.id,
            None,
            None,
            session_id,
            "anonymous-turn",
            now,
            required_intent_type="OPEN_SERVICE_NAVIGATION",
        )
    assert navigation.status == "ACTIVE"
    assert navigation.consumed_at is None

    navigation.prefill_json = {"service_id": str(uuid4())}
    result = await repository.consume_digital_human_intent(
        navigation.id,
        None,
        None,
        session_id,
        "anonymous-turn",
        now,
        required_intent_type="OPEN_SERVICE_NAVIGATION",
    )
    assert result["type"] == "OPEN_SERVICE_NAVIGATION"
    assert navigation.status == "CONSUMED"
    with pytest.raises(ConflictError):
        await repository.consume_digital_human_intent(
            navigation.id,
            None,
            None,
            session_id,
            "anonymous-replay",
            now,
            required_intent_type="OPEN_SERVICE_NAVIGATION",
        )

    expired = make_intent(
        owner_id=None,
        role=None,
        session_id=session_id,
        expires_at=now - timedelta(seconds=1),
    )
    expired.intent_type = "OPEN_SERVICE_NAVIGATION"
    expired.section = "services"
    expired.prefill_json = {"service_id": str(uuid4())}
    repository, _ = repository_with_intent(expired)
    with pytest.raises(ConflictError, match="已过期"):
        await repository.consume_digital_human_intent(
            expired.id,
            None,
            None,
            session_id,
            "anonymous-expired",
            now,
            required_intent_type="OPEN_SERVICE_NAVIGATION",
        )
    assert expired.status == "ACTIVE"


@pytest.mark.asyncio
async def test_intent_exchange_uses_owner_role_session_ttl_and_one_use_not_provider_chat_id() -> None:
    actor_id = uuid4()
    session_id = uuid4()
    record = make_intent(owner_id=actor_id, session_id=session_id)
    repository, audits = repository_with_intent(record)
    now = datetime.now(timezone.utc)

    result = await repository.consume_digital_human_intent(
        record.id,
        actor_id,
        Role.CITIZEN,
        session_id,
        "unrelated-per-turn-semantic-chat-hash",
        now,
    )

    assert result["intent_id"] == record.id
    assert record.status == "CONSUMED"
    assert record.consumed_at == now
    assert audits[-1]["detail"]["client_chat_id_hash"] == (
        "unrelated-per-turn-semantic-chat-hash"
    )
    with pytest.raises(ConflictError, match="已使用"):
        await repository.consume_digital_human_intent(
            record.id,
            actor_id,
            Role.CITIZEN,
            session_id,
            "another-turn",
            now,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["owner", "role", "session"])
async def test_intent_exchange_conceals_cross_owner_role_and_session(
    mismatch: str,
) -> None:
    owner_id = uuid4()
    session_id = uuid4()
    record = make_intent(owner_id=owner_id, session_id=session_id)
    repository, _ = repository_with_intent(record)

    with pytest.raises(ResourceNotFound):
        await repository.consume_digital_human_intent(
            record.id,
            uuid4() if mismatch == "owner" else owner_id,
            Role.STAFF if mismatch == "role" else Role.CITIZEN,
            uuid4() if mismatch == "session" else session_id,
            "client-chat-hash",
            datetime.now(timezone.utc),
        )
    assert record.status == "ACTIVE"


@pytest.mark.asyncio
async def test_intent_exchange_rejects_expired_intent_without_state_change() -> None:
    owner_id = uuid4()
    session_id = uuid4()
    record = make_intent(
        owner_id=owner_id,
        session_id=session_id,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    repository, _ = repository_with_intent(record)

    with pytest.raises(ConflictError, match="已过期"):
        await repository.consume_digital_human_intent(
            record.id,
            owner_id,
            Role.CITIZEN,
            session_id,
            "client-chat-hash",
            datetime.now(timezone.utc),
        )
    assert record.status == "ACTIVE"
