from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
class VisionTicketClaimsData:
    vision_session_id: UUID
    client_session_id: UUID
    account_id: UUID
    role: Role
    token_version: int


@dataclass(frozen=True, slots=True)
class VisionFrameData:
    vision_session_id: UUID
    client_session_id: UUID
    turn_sequence: int
    frame_sequence: int
    captured_at_ms: int
    received_at: datetime
    width: int
    height: int
    camera: Literal["front", "back"]
    jpeg: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class DocumentFrameData:
    """One user-triggered document photo kept only for the analysis call."""

    vision_session_id: UUID
    client_session_id: UUID
    document_sequence: int
    captured_at_ms: int
    received_at: datetime
    width: int
    height: int
    camera: Literal["front", "back"]
    jpeg: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class DocumentContextData:
    """Bounded, short-lived text understanding derived from one photo."""

    client_session_id: UUID
    document_sequence: int
    document_type: str
    summary: str
    visible_text: tuple[str, ...] = ()
    key_fields: tuple[str, ...] = ()
    confidence: float = 0.0
    mode: Literal["mock", "dashscope"] = "mock"
    # Opaque SHA-256 binding to the MetaStudio provider conversation. It is
    # never serialized into the model prompt or returned to Android.
    chat_binding: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class VisualContextData:
    client_session_id: UUID
    turn_sequence: int
    frame_count: int
    scene: str
    available: bool = True
    people: tuple[str, ...] = ()
    objects: tuple[str, ...] = ()
    visible_text: tuple[str, ...] = ()
    query_hints: tuple[str, ...] = ()
    confidence: float = 0.0
    mode: Literal["mock", "dashscope"] = "mock"


@dataclass(frozen=True, slots=True)
class VisionTurnSnapshotData:
    status: Literal["absent", "idle", "active", "ready"]
    client_session_id: UUID
    vision_session_id: UUID | None = None
    turn_sequence: int | None = None
    frames: tuple[VisionFrameData, ...] = ()


@dataclass(frozen=True, slots=True)
class NavigationCatalogRowData:
    line_number: int
    service_code: str
    window_code: str
    name: str
    address: str
    city_code: str
    longitude: float
    latitude: float
    coordinate_type: Literal["GCJ02"]
    opening_hours: str
    priority: int
    handling_mode: Literal["ONLINE_ONLY", "OFFLINE_ONLY", "BOTH", "UNKNOWN"]
    online_status: Literal["AVAILABLE", "TEMP_UNAVAILABLE", "UNKNOWN"]
    data_mode: Literal["DEMO", "VERIFIED"]
    source_reference: str | None
    verified_at: datetime | None


@dataclass(frozen=True, slots=True)
class ConversationMessageData:
    """One sanitized prior turn with its actual chat role preserved."""

    role: Literal["human", "ai"]
    content: str
    # Trusted server cards are carried only for deterministic continuation
    # (for example “那就生成吧”). The LLM adapter consumes role/content only.
    ui_cards: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ChatUiCardData:
    """A narrow, server-owned UI action rendered outside assistant prose.

    Cards deliberately carry no URL, object-store key, credential, arbitrary
    native command, or HTTP method.  The client can only feed the opaque intent
    or generation identifier into one of the fixed authenticated API routes.
    """

    type: Literal["MATERIAL_TEMPLATE"]
    state: str
    title: str
    notice: str
    service_title: str | None = None
    requirement_name: str | None = None
    requires_confirmation: bool = False
    intent_id: UUID | None = None
    generation_id: UUID | None = None
    expires_at: datetime | None = None


class ModelQuestion(str):
    """String-compatible model input carrying structured prior messages.

    The model port intentionally remains compatible with ordinary ``str``
    implementations.  ``LLMService`` reads this trusted metadata and emits
    real Human/AI messages instead of flattening history into the new user
    question.
    """

    conversation_history: tuple[ConversationMessageData, ...]

    def __new__(
        cls,
        content: str,
        conversation_history: tuple[ConversationMessageData, ...] = (),
    ) -> ModelQuestion:
        value = super().__new__(cls, content)
        value.conversation_history = tuple(conversation_history)
        return value


@dataclass(frozen=True, slots=True)
class ChatCommand:
    message: str
    request_id: UUID | None = None
    session_id: UUID | None = None
    service_id: UUID | None = None
    application_id: UUID | None = None
    # Sanitized prior messages supplied by trusted channel adapters. Retrieval
    # and cache keys continue to use only the current ``message``.
    conversation_history: tuple[ConversationMessageData, ...] = ()
    # A short-lived, sanitized snapshot derived from camera keyframes. Raw
    # frame bytes never enter chat persistence, public retrieval, or cache keys.
    visual_context: VisualContextData | None = None
    # A single-use, short-lived understanding of a user-triggered document
    # photo. The image and extracted text never enter retrieval or action
    # matching; this context is offered only to the answer model.
    document_context: DocumentContextData | None = None


@dataclass(slots=True)
class ChatResult:
    request_id: UUID
    session_id: UUID
    answer: str
    user_message_id: UUID | None = None
    assistant_message_id: UUID | None = None
    sources: list[SourceData] = field(default_factory=list)
    tool_calls: list[ToolCallData] = field(default_factory=list)
    cache_hit: bool = False
    warnings: list[str] = field(default_factory=list)
    candidate_services: list[dict[str, Any]] = field(default_factory=list)
    suggested_actions: list[dict[str, Any]] = field(default_factory=list)
    ui_cards: list[ChatUiCardData] = field(default_factory=list)
    clarification_required: bool = False
    handoff_status: str | None = None


@dataclass(frozen=True, slots=True)
class ConsultationMaterialIntentData:
    intent_id: UUID
    session_id: UUID
    service_id: UUID
    service_version_id: UUID
    requirement_code: str
    requirement_name: str
    template_id: UUID
    template_title: str
    status: Literal["PENDING", "CONFIRMED"]
    expires_at: datetime
    generation_id: UUID | None = None
