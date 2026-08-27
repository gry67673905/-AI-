"""Protocol mapping between HTTP Pydantic models and application dataclasses."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.application.dtos import (
    ChatCommand,
    ChatResult,
    ChatUiCardData,
    SourceData,
    ToolCallData,
)
from app.schemas import ChatRequest, ChatResponse, ChatUiCard, Source, ToolCall


def to_chat_command(payload: ChatRequest) -> ChatCommand:
    return ChatCommand(
        message=payload.message,
        session_id=payload.session_id,
        service_id=payload.service_id,
        application_id=payload.application_id,
    )


def source_payload(source: SourceData) -> dict[str, Any]:
    return asdict(source)


def ui_card_payload(card: ChatUiCardData) -> dict[str, Any]:
    """Serialize only the narrow card DTO; it has no generic URL/command field."""

    return ChatUiCard.model_validate(asdict(card)).model_dump(mode="json")


def to_chat_response(result: ChatResult) -> ChatResponse:
    return ChatResponse(
        request_id=result.request_id,
        session_id=result.session_id,
        user_message_id=result.user_message_id,
        assistant_message_id=result.assistant_message_id,
        answer=result.answer,
        sources=[Source.model_validate(asdict(item)) for item in result.sources],
        tool_calls=[
            ToolCall.model_validate(asdict(item)) for item in result.tool_calls
        ],
        cache_hit=result.cache_hit,
        warnings=result.warnings,
        candidate_services=result.candidate_services,
        suggested_actions=result.suggested_actions,
        ui_cards=[
            ChatUiCard.model_validate(asdict(item)) for item in result.ui_cards
        ],
        clarification_required=result.clarification_required,
        handoff_status=result.handoff_status,
    )
