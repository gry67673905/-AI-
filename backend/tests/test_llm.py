from __future__ import annotations

from app.llm import SYSTEM_PROMPT, build_messages
from app.application.dtos import SourceData as Source, ToolCallData as ToolCall


def test_prompt_contains_question_context_and_safety_rule() -> None:
    messages = build_messages(
        "补办身份证需要什么？",
        [Source(kind="rag", title="身份证补领", reference="demo://id", excerpt="本人办理")],
        [
            ToolCall(
                name="get_material_checklist",
                success=True,
                arguments={"itemId": 1002},
                result={"materials": ["身份证明"]},
            )
        ],
    )

    assert messages[0].content == SYSTEM_PROMPT
    assert "不可信数据" in str(messages[0].content)
    assert "补办身份证需要什么" in str(messages[1].content)
    assert "get_material_checklist" in str(messages[1].content)
