"""Protocol mapping between HTTP Pydantic models and application dataclasses."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.application.dtos import ChatCommand, ChatResult, SourceData, ToolCallData
from app.schemas import ChatRequest, ChatResponse, Source, ToolCall


def to_chat_command(payload: ChatRequest) -> ChatCommand:
    return ChatCommand(
        message=payload.message,
        session_id=payload.session_id,
        service_id=payload.service_id,
        application_id=payload.application_id,
    )


def source_payload(source: SourceData) -> dict[str, Any]:
    return asdict(source)


def to_chat_response(result: ChatResult) -> ChatResponse:
    return ChatResponse(
        request_id=result.request_id,
        session_id=result.session_id,
        answer=result.answer,
        sources=[Source.model_validate(asdict(item)) for item in result.sources],
        tool_calls=[
            ToolCall.model_validate(asdict(item)) for item in result.tool_calls
        ],
        cache_hit=result.cache_hit,
        warnings=result.warnings,
        candidate_services=result.candidate_services,
        suggested_actions=result.suggested_actions,
        clarification_required=result.clarification_required,
        handoff_status=result.handoff_status,
    )
