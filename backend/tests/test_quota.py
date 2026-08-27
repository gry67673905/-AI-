from __future__ import annotations

import hashlib
import hmac
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import Settings
from app.errors import TooManyRequests
from app.infrastructure.runtime import BusinessRuntime
from app.quota import ChatQuota


class FakeRedis:
    def __init__(self, result: list[int]) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, *args: object) -> list[int]:
        self.calls.append(args)
        return self.result

    async def aclose(self) -> None:
        return None


class FailingRedis(FakeRedis):
    async def eval(self, *args: object) -> list[int]:
        raise RedisConnectionError("synthetic outage")


@pytest.mark.asyncio
async def test_quota_hashes_identity_and_uses_atomic_script() -> None:
    quota = ChatQuota(
        "redis://unused",
        "test-hmac-key",
        enabled=True,
        anonymous_daily=10,
        authenticated_daily=30,
        global_daily=200,
    )
    fake = FakeRedis([1, 0, 1, 1])
    quota.client = fake  # type: ignore[assignment]
    account_id = uuid4()

    await quota.consume(account_id, "203.0.113.10")

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call[1] == 2
    serialized = " ".join(str(item) for item in call)
    assert str(account_id) not in serialized
    assert "203.0.113.10" not in serialized
    assert call[-2] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "message"),
    [
        ([0, 1, 200, 1], "总额度"),
        ([0, 2, 10, 10], "今日智能问答额度"),
    ],
)
async def test_quota_rejects_global_and_subject_limits(
    result: list[int], message: str
) -> None:
    quota = ChatQuota(
        "redis://unused",
        "test-hmac-key",
        enabled=True,
        anonymous_daily=10,
        authenticated_daily=30,
        global_daily=200,
    )
    quota.client = FakeRedis(result)  # type: ignore[assignment]

    with pytest.raises(TooManyRequests, match=message):
        await quota.consume(None, "203.0.113.10")


@pytest.mark.asyncio
async def test_disabled_quota_never_touches_redis() -> None:
    quota = ChatQuota(
        "redis://unused",
        "test-hmac-key",
        enabled=False,
        anonymous_daily=10,
        authenticated_daily=30,
        global_daily=200,
    )
    fake = FakeRedis([0, 1, 0, 0])
    quota.client = fake  # type: ignore[assignment]

    await quota.consume(None, "203.0.113.10")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_explicit_opaque_subject_exemption_bypasses_all_counters() -> None:
    hmac_key = "test-hmac-key"
    client_ip = "203.0.113.10"
    subject = hmac.new(
        hmac_key.encode("utf-8"),
        f"ip:{client_ip}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    quota = ChatQuota(
        "redis://unused",
        hmac_key,
        enabled=True,
        anonymous_daily=1,
        authenticated_daily=1,
        global_daily=1,
        exempt_subject_hashes={subject},
    )
    fake = FakeRedis([0, 1, 1, 1])
    quota.client = fake  # type: ignore[assignment]

    await quota.consume(None, client_ip)

    assert fake.calls == []


def test_quota_rejects_non_opaque_exemption_values() -> None:
    with pytest.raises(ValueError, match="invalid quota exemption subject"):
        ChatQuota(
            "redis://unused",
            "test-hmac-key",
            enabled=True,
            anonymous_daily=10,
            authenticated_daily=30,
            global_daily=200,
            exempt_subject_hashes={"203.0.113.10"},
        )


@pytest.mark.asyncio
async def test_enabled_quota_fails_closed_when_redis_is_unavailable() -> None:
    quota = ChatQuota(
        "redis://unused",
        "test-hmac-key",
        enabled=True,
        anonymous_daily=10,
        authenticated_daily=30,
        global_daily=200,
    )
    quota.client = FailingRedis([1, 0, 1, 1])  # type: ignore[assignment]

    with pytest.raises(Exception) as error:
        await quota.consume(None, "203.0.113.10")

    assert getattr(error.value, "code", None) == "chat_quota_unavailable"
    assert getattr(error.value, "status_code", None) == 503


@pytest.mark.asyncio
async def test_separate_quota_namespace_cannot_consume_chat_budget() -> None:
    quota = ChatQuota(
        "redis://unused",
        "test-hmac-key",
        enabled=True,
        anonymous_daily=5,
        authenticated_daily=10,
        global_daily=100,
        key_namespace="metastudio-session",
    )
    fake = FakeRedis([1, 0, 1, 1])
    quota.client = fake  # type: ignore[assignment]

    await quota.consume(None, "203.0.113.10")

    serialized = " ".join(str(item) for item in fake.calls[0])
    assert "quota:metastudio-session:" in serialized
    assert "quota:chat:" not in serialized


def test_demo_environment_requires_explicit_acknowledgement() -> None:
    settings = Settings(
        ENVIRONMENT="demo",
        ENABLE_DEMO_PROVIDERS=True,
        DEMO_PROVIDER_ACK="missing",
    )
    with pytest.raises(RuntimeError, match="DEMO_PROVIDER_ACK"):
        BusinessRuntime(settings, None, None, None, None, None, None)


def test_demo_environment_accepts_exact_acknowledgement() -> None:
    settings = Settings(
        ENVIRONMENT="demo",
        ENABLE_DEMO_PROVIDERS=True,
        DEMO_PROVIDER_ACK="I_ACKNOWLEDGE_DEMO_PROVIDERS",
    )
    runtime = BusinessRuntime(settings, None, None, None, None, None, None)
    assert runtime.sms.enabled is True
    assert runtime.metastudio.vision is runtime.vision
    assert runtime.vision._authorize_client_session.__self__ is runtime.metastudio
    assert runtime.vision_analysis_quota is None
    assert not hasattr(runtime.vision_analyzer, "_quota")


@pytest.mark.asyncio
async def test_dashscope_runtime_wires_global_quota_only_to_real_provider() -> None:
    settings = Settings(
        ENVIRONMENT="local",
        ENABLE_DEMO_PROVIDERS=False,
        VISION_PROVIDER="dashscope",
        VISION_DASHSCOPE_API_KEY="test-only-vision-key",
        VISION_ANALYSIS_GLOBAL_DAILY=37,
    )
    runtime = BusinessRuntime(settings, None, None, None, None, None, None)

    assert runtime.vision_analysis_quota is not None
    assert runtime.vision_analyzer._quota is runtime.vision_analysis_quota
    assert runtime.vision_analysis_quota._daily_limit == 37

    await runtime.close()
