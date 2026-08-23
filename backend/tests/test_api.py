from __future__ import annotations

from dataclasses import replace
from typing import Any
from types import SimpleNamespace
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from app.domain.policies import DomainRuleViolation
from app.infrastructure.providers import DemoProviderDisabled

from app.errors import DatabaseUnavailable, LLMUnavailable, TooManyRequests
from app.chat import ChatExecutionContext, handle_chat
from app.application.coordinators import ConsultationCoordinator
from app.application.dtos import (
    KnowledgeSearchResult,
    Principal,
    SourceData as Source,
    ToolCallData as ToolCall,
)
from app.domain.enums import ApplicantType, Role
from app.main import create_app
from app.schemas import ChatRequest, HealthCheck
from app.security import redact_pii_text


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
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, _message: str, _context_id: object = None) -> tuple[list[Source], list[ToolCall]] | None:
        self.get_calls += 1
        if self.value is None:
            return None
        sources, calls = self.value
        return sources, [replace(call, cached=True) for call in calls]

    async def set(self, _message: str, sources: list[Source], calls: list[ToolCall], _context_id: object = None) -> None:
        self.set_calls += 1
        self.value = (sources, calls)


class FakeMCP:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.selected_service_ids: list[int | None] = []
        self.queries: list[str] = []

    async def retrieve(self, _query: str, _selected_service_id: int | None = None, _allow_inferred_details: bool = True):
        self.calls += 1
        self.selected_service_ids.append(_selected_service_id)
        self.queries.append(_query)
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
        self.questions: list[str] = []
        self.source_batches: list[list[Source]] = []

    async def answer(self, _question: str, _sources: list, _calls: list, request_id):
        self.questions.append(_question)
        self.source_batches.append(list(_sources))
        if self.fail:
            raise LLMUnavailable(request_id)
        return "演示回答；实际要求以当地规定为准。"


class FakeChatRepository:
    async def list_services(
        self, _query: str | None = None, _include_all: bool = False
    ) -> list[dict[str, Any]]:
        return []


class FakeChatSecurity:
    @staticmethod
    def redact_public_text(value: str) -> str:
        return redact_pii_text(value)


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
        self.chat = ConsultationCoordinator(
            FakeChatRepository(),  # type: ignore[arg-type]
            self.database,
            self.cache,
            self.mcp,
            self.milvus,
            self.llm,
            FakeChatSecurity(),  # type: ignore[arg-type]
        )
        self.business = SimpleNamespace(consultations=self.chat)

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


def test_group_rag_notice_is_added_on_fresh_and_cached_results() -> None:
    class GroupKnowledge:
        async def search_with_warnings(self, _query: str) -> KnowledgeSearchResult:
            return KnowledgeSearchResult(
                sources=[
                    Source(
                        kind="rag",
                        title="组员语料",
                        reference="ragdb://v1/t01/t01-000-00",
                        excerpt="组员演示资料",
                    )
                ]
            )

    services = FakeServices()
    services.chat.knowledge = GroupKnowledge()  # type: ignore[assignment]
    with TestClient(create_app(services)) as client:
        first = client.post("/api/v1/chat", json={"message": "社保卡怎么办"})
        second = client.post("/api/v1/chat", json={"message": "社保卡怎么办"})

    assert first.status_code == 200
    assert services.cache.set_calls == 1
    assert any(
        warning.startswith("rag_group_demo_unverified:")
        for warning in first.json()["warnings"]
    )
    assert any(
        warning.startswith("rag_group_demo_unverified:")
        for warning in second.json()["warnings"]
    )


def test_chat_stream_maps_application_dataclasses_to_sse() -> None:
    services = FakeServices()
    with TestClient(create_app(services)) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "社保卡怎么办"})

    assert response.status_code == 200
    assert "event: meta" in response.text
    assert '"kind": "mcp"' in response.text
    assert "event: delta" in response.text
    assert "event: done" in response.text


def test_chat_quota_failure_is_structured_429_for_json_and_stream() -> None:
    class RejectingQuota:
        async def consume(self, _account_id: object, _client_ip: str) -> None:
            raise TooManyRequests()

    services = FakeServices()
    services.chat_quota = RejectingQuota()  # type: ignore[attr-defined]
    with TestClient(create_app(services)) as client:
        json_response = client.post(
            "/api/v1/chat", json={"message": "社保卡怎么办"}
        )
        stream_response = client.post(
            "/api/v1/chat/stream", json={"message": "社保卡怎么办"}
        )

    assert json_response.status_code == 429
    assert json_response.json()["error"]["code"] == "chat_quota_exceeded"
    assert stream_response.status_code == 429
    assert stream_response.json()["error"]["code"] == "chat_quota_exceeded"


def test_retrieval_dependencies_degrade_with_warnings() -> None:
    services = FakeServices(mcp_fail=True, milvus_fail=True)
    with TestClient(create_app(services)) as client:
        response = client.post("/api/v1/chat", json={"message": "办理事项"})

    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert len(response.json()["warnings"]) == 3
    assert any(
        item.startswith("grounding_unavailable:")
        for item in response.json()["warnings"]
    )
    assert "暂不调用大模型" in response.json()["answer"]
    assert services.llm.questions == []


def test_database_failure_is_structured_503() -> None:
    with TestClient(create_app(FakeServices(database_fail=True))) as client:
        response = client.post("/api/v1/chat", json={"message": "办理事项"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert response.json()["error"]["request_id"] is not None


def test_raw_sqlalchemy_failure_is_structured_503() -> None:
    application = create_app(FakeServices())

    @application.get("/_test/database-failure")
    async def database_failure() -> None:
        raise SQLAlchemyError("synthetic database outage")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/_test/database-failure")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"


def test_runtime_domain_rule_failure_is_structured_422() -> None:
    application = create_app(FakeServices())

    @application.get("/_test/domain-rule-failure")
    async def domain_rule_failure() -> None:
        raise DomainRuleViolation("in 第二个参数必须是非空集合")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/_test/domain-rule-failure")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "business_validation_failed"


def test_disabled_demo_provider_is_structured_503() -> None:
    application = create_app(FakeServices())

    @application.get("/_test/provider-disabled")
    async def provider_disabled() -> None:
        raise DemoProviderDisabled()

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/_test/provider-disabled")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "demo_provider_unavailable"


def test_llm_failure_is_structured_502() -> None:
    with TestClient(create_app(FakeServices(llm_fail=True))) as client:
        response = client.post("/api/v1/chat", json={"message": "办理事项"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_unavailable"
    assert response.json()["error"]["request_id"] is not None


@pytest.mark.asyncio
async def test_ambiguous_chat_is_deterministic_and_skips_retrieval_and_llm() -> None:
    services = FakeServices()
    context = ChatExecutionContext(
        candidates=[
            {"id": uuid4(), "title": "社会保障卡申领"},
            {"id": uuid4(), "title": "企业社会保险登记"},
        ],
        clarification_required=True,
    )
    result = await handle_chat(ChatRequest(message="社保怎么办"), services.chat, context)
    assert "请先选择" in result.answer
    assert result.suggested_actions[0]["type"] == "SELECT_SERVICE"
    assert services.cache.get_calls == 0
    assert services.mcp.calls == 0
    assert services.llm.questions == []


@pytest.mark.asyncio
async def test_selected_service_drives_mcp_and_private_case_bypasses_cache() -> None:
    services = FakeServices()
    context = ChatExecutionContext(
        external_item_id=1002,
        public_service={"id": uuid4(), "title": "居民身份证丢失补领"},
        private_case={"service_title": "居民身份证丢失补领", "status": "IN_REVIEW"},
    )
    result = await handle_chat(ChatRequest(message="进度如何"), services.chat, context)
    assert result.cache_hit is False
    assert services.cache.get_calls == 0
    assert services.cache.set_calls == 0
    assert services.mcp.selected_service_ids == []
    assert services.llm.questions == []
    assert "审核中" in result.answer
    assert "未发送给大模型" in result.answer


@pytest.mark.asyncio
async def test_private_case_uses_pinned_version_when_catalogue_is_not_public() -> None:
    services = FakeServices()
    application_id = uuid4()
    service_id = uuid4()

    class Repository(FakeChatRepository):
        async def get_application_case_authorized(self, *_args, **_kwargs):
            return {
                "id": application_id,
                "service_id": service_id,
                "service_version_id": uuid4(),
                "service_code": "RETIRED-DEMO-001",
                "service_title": "已终止事项的历史办件",
                "service_summary": "办件创建时固定的公开演示版本。",
                "external_item_id": None,
                "status": "IN_REVIEW",
            }

        async def get_service_bundle(self, *_args, **_kwargs):
            raise AssertionError("private case must not query the live public catalogue")

    services.chat.repository = Repository()  # type: ignore[assignment]
    principal = Principal(
        account_id=uuid4(),
        username="citizen",
        display_name="演示群众",
        role=Role.CITIZEN,
        applicant_type=ApplicantType.INDIVIDUAL,
        token_version=0,
    )

    result = await handle_chat(
        ChatRequest(message="历史办件进度", application_id=application_id),
        services.chat,
        principal=principal,
    )

    assert "已终止事项的历史办件" in result.answer
    assert "审核中" in result.answer
    assert services.mcp.calls == 0
    assert services.llm.questions == []


@pytest.mark.asyncio
async def test_public_selected_service_uses_exact_external_id_and_context_cache() -> None:
    services = FakeServices()
    context = ChatExecutionContext(
        external_item_id=1005,
        public_service={
            "id": uuid4(),
            "title": "劳动合同备案",
            "code": "DEMO-LABOR-CONTRACT-001",
            "summary": "用人单位提交劳动合同备案材料。",
            "internal_note": "不得进入模型或响应来源",
        },
    )
    result = await handle_chat(ChatRequest(message="怎么办"), services.chat, context)
    assert services.mcp.selected_service_ids == [1005]
    assert services.mcp.queries == ["劳动合同备案 DEMO-LABOR-CONTRACT-001"]
    assert services.cache.get_calls == 1
    assert services.cache.set_calls == 1
    local_sources = [item for item in result.sources if item.kind == "local_catalog"]
    assert len(local_sources) == 1
    assert local_sources[0].reference.startswith("local-catalog://services/")
    assert "劳动合同备案" in local_sources[0].excerpt
    assert "不得进入模型或响应来源" not in local_sources[0].excerpt
    assert any(item.kind == "local_catalog" for item in services.llm.source_batches[0])


@pytest.mark.asyncio
async def test_unmapped_local_service_skips_mcp_and_never_puts_none_in_prompt() -> None:
    services = FakeServices()
    context = ChatExecutionContext(
        public_service={
            "id": uuid4(),
            "title": "管理员新建的本地演示事项",
            "code": "LOCAL-DEMO-001",
        },
    )

    result = await handle_chat(ChatRequest(message="怎么办"), services.chat, context)

    assert services.mcp.calls == 0
    assert services.llm.questions
    assert "外部演示事项ID None" not in services.llm.questions[0]
    assert any(item.startswith("mcp_unmapped:") for item in result.warnings)


@pytest.mark.asyncio
async def test_public_question_pii_is_not_sent_to_retrieval_or_llm() -> None:
    services = FakeServices()
    await handle_chat(
        ChatRequest(
            message=(
                "未知事项，联系13800138000，证件110101199001011234，"
                "邮箱demo@example.com"
            )
        ),
        services.chat,
    )

    assert services.mcp.queries
    assert services.llm.questions
    combined = services.mcp.queries[0] + services.llm.questions[0]
    assert "13800138000" not in combined
    assert "110101199001011234" not in combined
    assert "demo@example.com" not in combined
