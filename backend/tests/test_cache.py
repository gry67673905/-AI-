from __future__ import annotations

import pytest

from app.cache import RetrievalCache
from app.application.dtos import SourceData as Source, ToolCallData as ToolCall


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.values[key] = value


@pytest.mark.asyncio
async def test_retrieval_cache_round_trip_marks_tool_calls_cached() -> None:
    cache = RetrievalCache("redis://unused:6379/0", ttl_seconds=300)
    cache.client = FakeRedis()  # type: ignore[assignment]
    source = Source(kind="rag", title="演示", reference="demo://one", excerpt="资料")
    call = ToolCall(
        name="search_services",
        success=True,
        arguments={"keyword": "社保卡"},
        result={"id": 1001},
        duration_ms=5,
    )

    assert await cache.get("社保卡怎么办") is None
    await cache.set("社保卡怎么办", [source], [call])
    cached = await cache.get("社保卡怎么办")

    assert cached is not None
    assert cached[0] == [source]
    assert cached[1][0].cached is True
    assert cached[1][0].arguments == {}
    assert cached[1][0].result == {"id": 1001}


@pytest.mark.asyncio
async def test_public_cache_never_serializes_tool_arguments_or_pii() -> None:
    cache = RetrievalCache("redis://unused:6379/0", ttl_seconds=300)
    fake = FakeRedis()
    cache.client = fake  # type: ignore[assignment]
    call = ToolCall(
        name="search_services",
        success=True,
        arguments={"keyword": "13800138000 demo@example.com"},
        result={"id": 1001, "echo": "联系13800138000"},
    )
    source = Source(
        kind="mcp", title="演示", reference="demo://one",
        excerpt="身份证110101199001011234",
    )

    await cache.set("手机号13800138000", [source], [call])
    serialized = next(iter(fake.values.values()))

    assert "13800138000" not in serialized
    assert "110101199001011234" not in serialized
    assert "demo@example.com" not in serialized


def test_cache_key_normalizes_equivalent_text() -> None:
    assert RetrievalCache.key_for(" 社保卡  办理 ") == RetrievalCache.key_for("社保卡 办理")
    assert RetrievalCache.key_for("社保卡办理", 1001) != RetrievalCache.key_for("社保卡办理", 1002)
    assert RetrievalCache.key_for("社保卡办理").startswith("smart-gov:retrieval:v3:")
    assert RetrievalCache.key_for(
        "社保卡办理", dataset_version="2026.08"
    ) != RetrievalCache.key_for("社保卡办理", dataset_version="2026.09")
