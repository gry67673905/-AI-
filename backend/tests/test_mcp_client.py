from __future__ import annotations

from types import SimpleNamespace

from app.mcp_client import decode_tool_result, normalize_mcp_keyword


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
