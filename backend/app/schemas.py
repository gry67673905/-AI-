from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    session_id: UUID | None = None
    message: str = Field(min_length=1, max_length=1000)
    service_id: UUID | None = None
    application_id: UUID | None = None

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message 不能为空")
        return value


class Source(BaseModel):
    kind: Literal["mcp", "rag", "local_catalog"]
    title: str
    reference: str
    excerpt: str
    score: float | None = None


class ToolCall(BaseModel):
    name: str
    success: bool
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    duration_ms: int = 0
    cached: bool = False
    error: str | None = None


class ChatUiCard(BaseModel):
    """A fixed, URL-free action descriptor rendered by trusted client code."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["MATERIAL_TEMPLATE"]
    state: Literal[
        "AVAILABLE",
        "CONFIRMATION_REQUIRED",
        "QUEUED",
        "RUNNING",
        "READY",
        "FAILED",
        "EXPIRED",
    ]
    title: str
    notice: str
    service_title: str | None = None
    requirement_name: str | None = None
    requires_confirmation: bool = False
    intent_id: UUID | None = None
    generation_id: UUID | None = None
    expires_at: datetime | None = None


class ChatResponse(BaseModel):
    request_id: UUID
    session_id: UUID
    user_message_id: UUID | None = None
    assistant_message_id: UUID | None = None
    answer: str
    sources: list[Source] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    cache_hit: bool
    warnings: list[str] = Field(default_factory=list)
    candidate_services: list[dict[str, Any]] = Field(default_factory=list)
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list)
    ui_cards: list[ChatUiCard] = Field(default_factory=list)
    clarification_required: bool = False
    handoff_status: str | None = None


class ConsultationMessage(BaseModel):
    id: UUID
    request_id: UUID
    role: Literal["user", "assistant"]
    content: str
    ui_cards: list[ChatUiCard] = Field(default_factory=list)
    created_at: datetime


class ConsultationMessagePage(BaseModel):
    session_id: UUID
    items: list[ConsultationMessage] = Field(default_factory=list)
    next_before: UUID | None = None
    has_more: bool = False


class HealthCheck(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: int
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, HealthCheck]


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: UUID | None = None
    detail: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
