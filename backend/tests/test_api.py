from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.errors import DatabaseUnavailable, LLMUnavailable
from app.main import create_app
from app.schemas import HealthCheck, Source, ToolCall


class FakeDatabase:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.user_messages: list[tuple[Any, ...]] = []
        self.answers: list[tuple[Any, ...]] = []

    async def save_user_message(self, *args: Any) -> None:
        if self.fail:
            raise DatabaseUnavailable(args[1])
        self.user_messages.append(args)

    async def save_assistant_result(self, *args: Any) -> None:
        if self.fail:
            raise DatabaseUnavailable(args[1])
        self.answers.append(args)


class FakeCache:
    def __init__(self) -> None:
        self.value: tuple[list[Source], list[ToolCall]] | None = None

    async def get(self, _message: str) -> tuple[list[Source], list[ToolCall]] | None:
        if self.value is None:
            return None
        sources, calls = self.value
        return sources, [call.model_copy(update={"cached": True}) for call in calls]

    async def set(self, _message: str, sources: list[Source], calls: list[ToolCall]) -> None:
        self.value = (sources, calls)


class FakeMCP:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def retrieve(self, _query: str):
        self.calls += 1
        if self.fail:
            raise RuntimeError("MCP down")
        call = ToolCall(
            name="search_services",
            success=True,
            arguments={"keyword": "社保卡"},
            result={"items": [{"id": 1001}]},
        )
        source = Source(
            kind="mcp", title="事项检索", reference="mcp:search_services", excerpt="社保卡"
        )
        return [source], [call], []


class FakeMilvus:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def search(self, _query: str) -> list[Source]:
        if self.fail:
            raise RuntimeError("Milvus down")
        return [
            Source(kind="rag", title="演示知识", reference="demo://rag", excerpt="演示内容")
        ]


class FakeLLM:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def answer(self, _question: str, _sources: list, _calls: list, request_id):
        if self.fail:
            raise LLMUnavailable(request_id)
        return "演示回答；实际要求以当地规定为准。"


class FakeServices:
    def __init__(
        self,
        *,
        database_fail: bool = False,
        llm_fail: bool = False,
        mcp_fail: bool = False,
        milvus_fail: bool = False,
    ) -> None:
        self.database = FakeDatabase(database_fail)
        self.cache = FakeCache()
        self.mcp = FakeMCP(mcp_fail)
        self.milvus = FakeMilvus(milvus_fail)
        self.llm = FakeLLM(llm_fail)

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def readiness(self) -> dict[str, HealthCheck]:
        return {
            name: HealthCheck(status="ok", latency_ms=1)
            for name in ("postgres", "redis", "milvus", "mcp", "mock_gov_api")
        }


def test_live_and_request_validation() -> None:
    with TestClient(create_app(FakeServices())) as client:
        assert client.get("/health/live").status_code == 200
        assert client.post("/api/v1/chat", json={"message": "   "}).status_code == 422
        assert client.post("/api/v1/chat", json={"message": "x" * 1001}).status_code == 422


def test_readiness_is_503_when_any_dependency_is_down() -> None:
    services = FakeServices()

    async def not_ready() -> dict[str, HealthCheck]:
        return {
            "postgres": HealthCheck(status="ok", latency_ms=1),
            "redis": HealthCheck(status="error", latency_ms=1, detail="unavailable"),
            "milvus": HealthCheck(status="ok", latency_ms=1),
            "mcp": HealthCheck(status="ok", latency_ms=1),
            "mock_gov_api": HealthCheck(status="ok", latency_ms=1),
        }

    services.readiness = not_ready  # type: ignore[method-assign]
    with TestClient(create_app(services)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["redis"]["status"] == "error"


def test_chat_runs_full_path_then_uses_cache() -> None:
    services = FakeServices()
    with TestClient(create_app(services)) as client:
        first = client.post("/api/v1/chat", json={"message": "社保卡怎么办"})
        second = client.post("/api/v1/chat", json={"message": "社保卡怎么办"})

    assert first.status_code == 200
    assert first.json()["cache_hit"] is False
    assert {source["kind"] for source in first.json()["sources"]} == {"mcp", "rag"}
    assert second.status_code == 200
    assert second.json()["cache_hit"] is True
    assert second.json()["tool_calls"][0]["cached"] is True
    assert services.mcp.calls == 1
    assert len(services.database.user_messages) == 2
    assert len(services.database.answers) == 2


def test_retrieval_dependencies_degrade_with_warnings() -> None:
    with TestClient(create_app(FakeServices(mcp_fail=True, milvus_fail=True))) as client:
        response = client.post("/api/v1/chat", json={"message": "办理事项"})

    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert len(response.json()["warnings"]) == 2


def test_database_failure_is_structured_503() -> None:
    with TestClient(create_app(FakeServices(database_fail=True))) as client:
        response = client.post("/api/v1/chat", json={"message": "办理事项"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert response.json()["error"]["request_id"] is not None


def test_llm_failure_is_structured_502() -> None:
    with TestClient(create_app(FakeServices(llm_fail=True))) as client:
        response = client.post("/api/v1/chat", json={"message": "办理事项"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_unavailable"
    assert response.json()["error"]["request_id"] is not None
