from __future__ import annotations

from types import SimpleNamespace

from app.mcp_client import decode_tool_result, normalize_mcp_keyword, select_service, select_service_id


def test_decode_tool_result_removes_exactly_one_json_layer() -> None:
    result = SimpleNamespace(
        structuredContent=None,
        content=[SimpleNamespace(text='{"value":"{\\"nested\\":true}"}')],
    )

    assert decode_tool_result(result) == {"value": '{"nested":true}'}


def test_decode_tool_result_prefers_structured_content() -> None:
    result = SimpleNamespace(
        structuredContent={"services": [{"id": 1001}]},
        content=[SimpleNamespace(text="ignored")],
    )

    assert decode_tool_result(result) == {"services": [{"id": 1001}]}


def test_mcp_keyword_respects_reused_server_schema_limit() -> None:
    assert normalize_mcp_keyword("  " + "政" * 120 + "  ") == "政" * 100


def test_mcp_keyword_extracts_demo_service_from_natural_question() -> None:
    assert normalize_mcp_keyword("办理社会保障卡需要准备哪些材料？") == "社会保障卡"
    assert normalize_mcp_keyword("我的身份证丢失了怎么办") == "身份证"
    assert normalize_mcp_keyword("企业如何办理劳动合同备案") == "劳动合同"
    assert normalize_mcp_keyword("企业社保登记怎么办") == "企业社会保险"
    assert normalize_mcp_keyword("个体户注册怎么办") == "个体工商户"


def test_unknown_mcp_keyword_redacts_pii_before_tool_invocation() -> None:
    keyword = normalize_mcp_keyword(
        "未知事项，手机13800138000，号码110101199001011234，邮箱demo@example.com"
    )
    assert "13800138000" not in keyword
    assert "110101199001011234" not in keyword
    assert "demo@example.com" not in keyword
    assert "[REDACTED_PHONE]" in keyword


def test_select_service_scores_intent_instead_of_first_result() -> None:
    result = {
        "items": [
            {"id": 1001, "name": "社会保障卡申领"},
            {"id": 1004, "name": "企业社会保险登记"},
            {"id": 1005, "name": "劳动合同备案"},
        ]
    }
    assert select_service_id(result, "企业如何办理劳动合同备案", "劳动合同") == 1005
    assert select_service_id(result, "企业社保登记怎么办", "企业社会保险") == 1004


def test_generic_social_security_query_requires_clarification() -> None:
    result = {
        "items": [
            {"id": 1001, "name": "社会保障卡申领"},
            {"id": 1004, "name": "企业社会保险登记"},
        ]
    }
    selected, ambiguous, candidates = select_service(result, "社保怎么办", "社保")
    assert selected is None
    assert ambiguous is True
    assert len(candidates) == 2
