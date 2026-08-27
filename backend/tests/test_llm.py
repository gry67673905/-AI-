from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.llm import LLMService, SYSTEM_PROMPT, build_messages
from app.application.dtos import (
    ConversationMessageData,
    ModelQuestion,
    Principal,
    SourceData as Source,
    ToolCallData as ToolCall,
)
from app.application.coordinators import ConsultationCoordinator
from app.domain.enums import ApplicantType, Role


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


def test_prompt_preserves_human_ai_roles_and_natural_response_policy() -> None:
    question = ModelQuestion(
        "那接下来呢？",
        (
            ConversationMessageData(role="human", content="我想补办社保卡"),
            ConversationMessageData(role="ai", content="可以，我先帮你确认事项。"),
        ),
    )

    messages = build_messages(question, [], [])

    assert [type(message) for message in messages] == [
        SystemMessage,
        HumanMessage,
        AIMessage,
        HumanMessage,
    ]
    assert messages[1].content == "我想补办社保卡"
    assert messages[2].content == "可以，我先帮你确认事项。"
    assert "当前用户问题：那接下来呢" in str(messages[3].content)
    assert "不套用固定字数上限或下限" in SYSTEM_PROMPT
    assert "不机械复述" in SYSTEM_PROMPT
    assert "绝不能根据人脸" in SYSTEM_PROMPT
    assert "不要每句话都称呼用户" in SYSTEM_PROMPT


def test_authenticated_profile_is_redacted_bounded_and_tone_only() -> None:
    coordinator = object.__new__(ConsultationCoordinator)
    coordinator.security = SimpleNamespace(
        redact_public_text=lambda value: str(value).replace(
            "sk-private", "[REDACTED_SECRET]"
        )
    )
    principal = Principal(
        account_id=uuid4(),
        username="not-sent-to-model",
        display_name="小林 sk-private" + "很长" * 80,
        role=Role.CITIZEN,
        applicant_type=ApplicantType.INDIVIDUAL,
        token_version=1,
    )

    prompt = coordinator._conversation_profile_prompt(principal)

    assert prompt is not None
    profile = json.loads(prompt.rsplit("\n", 1)[1])
    assert len(profile["display_name"]) <= 64
    assert "sk-private" not in prompt
    assert profile["role"] == "CITIZEN"
    assert profile["applicant_type"] == "INDIVIDUAL"
    assert "not-sent-to-model" not in prompt
    assert "不是资格、权限或政策事实" in prompt
    assert "不得用人脸推断身份" in prompt


@pytest.mark.asyncio
async def test_answer_uses_exactly_one_model_call_without_rewrite() -> None:
    class CountingModel:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return SimpleNamespace(content="可以，先带身份证明去办理。")

    service = LLMService(
        mode="deepseek",
        model="deepseek-v4-flash",
        api_key="unit-test-no-egress-key",
        timeout_seconds=1,
        max_retries=0,
    )
    model = CountingModel()
    service._model = model

    answer = await service.answer("怎么办？", [], [], uuid4())

    assert answer == "可以，先带身份证明去办理。"
    assert model.calls == 1


def test_deepseek_v4_flash_payload_disables_thinking_without_network() -> None:
    service = LLMService(
        mode="deepseek",
        model="deepseek-v4-flash",
        api_key="unit-test-no-egress-key",
        timeout_seconds=1,
        max_retries=0,
    )

    model = service._get_model()
    payload = model._get_invocation_params()

    assert payload["model"] == "deepseek-v4-flash"
    assert payload["thinking"] == {"type": "disabled"}
