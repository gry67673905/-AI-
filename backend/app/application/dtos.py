from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from app.domain.enums import ApplicantType, Role


@dataclass(frozen=True, slots=True)
class Principal:
    account_id: UUID
    username: str
    display_name: str
    role: Role
    applicant_type: ApplicantType | None
    token_version: int
    department_id: UUID | None = None


@dataclass(slots=True)
class ChatExecutionContext:
    owner_account_id: UUID | None = None
    external_item_id: int | None = None
    public_service: dict[str, Any] | None = None
    private_case: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    clarification_required: bool = False


@dataclass(frozen=True, slots=True)
class SourceData:
    kind: Literal["mcp", "rag", "local_catalog"]
    title: str
    reference: str
    excerpt: str
    score: float | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeSearchResult:
    """Grounding sources plus non-fatal retrieval degradation warnings."""

    sources: list[SourceData] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ToolCallData:
    name: str
    success: bool
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    duration_ms: int = 0
    cached: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ChatCommand:
    message: str
    session_id: UUID | None = None
    service_id: UUID | None = None
    application_id: UUID | None = None
    # Sanitized alternating question/answer messages supplied by trusted
    # channel adapters. Retrieval and cache keys continue to use ``message``.
    conversation_history: tuple[str, ...] = ()


@dataclass(slots=True)
class ChatResult:
    request_id: UUID
    session_id: UUID
    answer: str
    sources: list[SourceData] = field(default_factory=list)
    tool_calls: list[ToolCallData] = field(default_factory=list)
    cache_hit: bool = False
    warnings: list[str] = field(default_factory=list)
    candidate_services: list[dict[str, Any]] = field(default_factory=list)
    suggested_actions: list[dict[str, Any]] = field(default_factory=list)
    clarification_required: bool = False
    handoff_status: str | None = None
