from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Protocol
from uuid import UUID

from app.application.dtos import (
    ChatUiCardData,
    ConversationMessageData,
    DocumentContextData,
    DocumentFrameData,
    NavigationCatalogRowData,
    Principal,
    SourceData,
    ToolCallData,
    VisualContextData,
    VisionFrameData,
    VisionTurnSnapshotData,
    VisionTicketClaimsData,
)
from app.application.rag_dtos import (
    CorpusArchiveData,
    CorpusChunkData,
    CorpusDatasetSpec,
    CorpusDatasetState,
    CorpusRouteData,
)

from app.domain.enums import (
    ApplicantType,
    AppointmentStatus,
    ApplicationStatus,
    DeliveryStatus,
    Role,
    ServiceStatus,
)


class AccountCredentialPort(Protocol):
    id: UUID
    username: str
    display_name: str
    password_hash: str
    role: str
    applicant_type: str | None
    active: bool
    token_version: int
    department_id: UUID | None


class BusinessRepositoryPort(Protocol):
    """Persistence gateway consumed by use-case coordinators.

    SQLAlchemy records and sessions remain implementation details of the
    infrastructure adapter. This modular monolith keeps a broad gateway that
    can later be split by aggregate without changing the dependency direction.
    """

    async def create_account(
        self, username: str, password_hash: str, display_name: str,
        applicant_type: ApplicantType, role: Role = Role.CITIZEN,
        department_id: UUID | None = None,
    ) -> AccountCredentialPort: ...
    async def get_account_by_username(self, username: str) -> AccountCredentialPort | None: ...
    async def get_account_record(self, account_id: UUID) -> AccountCredentialPort | None: ...
    async def get_account_view(self, account_id: UUID) -> dict[str, Any]: ...
    async def save_refresh_token(self, account_id: UUID, token: str, expires_at: datetime) -> None: ...
    async def save_refresh_token_if_current(self, account_id: UUID, expected_token_version: int, token: str, expires_at: datetime) -> None: ...
    async def consume_refresh_token(self, token: str) -> AccountCredentialPort | None: ...
    async def revoke_refresh_token(self, token: str) -> None: ...
    async def get_idempotent(self, actor_id: UUID, scope: str, key: str, request_hash: str) -> dict[str, Any] | None: ...
    async def store_idempotent(self, actor_id: UUID, scope: str, key: str, request_hash: str, response: dict[str, Any]) -> dict[str, Any]: ...
    async def execute_idempotent(
        self, actor_id: UUID, scope: str, key: str, request_hash: str,
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]: ...
    async def list_services(self, query: str | None = None, include_all: bool = False) -> list[dict[str, Any]]: ...
    async def get_service_bundle(self, service_id: UUID, include_all: bool = False) -> dict[str, Any]: ...
    async def create_department(self, actor_id: UUID, code: str, name: str) -> dict[str, Any]: ...
    async def list_departments(self) -> list[dict[str, Any]]: ...
    async def create_window(self, actor_id: UUID, values: dict[str, Any]) -> dict[str, Any]: ...
    async def list_windows(self, department_id: UUID | None = None) -> list[dict[str, Any]]: ...
    async def get_navigation_options(self, service_id: UUID) -> dict[str, Any]: ...
    async def import_navigation_catalog(
        self,
        actor_id: UUID,
        rows: tuple[NavigationCatalogRowData, ...],
        dry_run: bool,
    ) -> dict[str, Any]: ...
    async def create_staff_account(
        self, actor_id: UUID, username: str, password_hash: str,
        display_name: str, department_id: UUID, window_id: UUID | None,
    ) -> dict[str, Any]: ...
    async def list_accounts(self) -> list[dict[str, Any]]: ...
    async def set_account_active(self, actor_id: UUID, account_id: UUID, active: bool) -> dict[str, Any]: ...
    async def create_service(self, actor_id: UUID, values: dict[str, Any]) -> dict[str, Any]: ...
    async def create_service_version(self, actor_id: UUID, service_id: UUID, values: dict[str, Any]) -> dict[str, Any]: ...
    async def transition_service(
        self, actor_id: UUID, service_id: UUID, target: ServiceStatus,
        version_id: UUID | None,
    ) -> dict[str, Any]: ...
    async def list_audits(self, limit: int = 100) -> list[dict[str, Any]]: ...
    async def metrics(self) -> dict[str, int]: ...
    async def get_material_entities(self, service_id: UUID) -> tuple[dict[str, Any], list[Any]]: ...
    async def list_material_template_options(
        self, application_id: UUID, owner_account_id: UUID
    ) -> list[dict[str, Any]]: ...
    async def list_consultation_material_template_options(
        self, service_id: UUID | None = None, query: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def search_consultation_material_template_options(
        self, query: str
    ) -> list[dict[str, Any]]: ...
    async def create_consultation_material_intent(
        self,
        owner_account_id: UUID,
        session_id: UUID,
        service_id: UUID,
        requirement_code: str,
        template_id: UUID,
        request_text: str | None,
        expires_at: datetime,
    ) -> dict[str, Any]: ...
    async def get_consultation_material_intent_states(
        self,
        owner_account_id: UUID,
        session_id: UUID,
        intent_ids: tuple[UUID, ...],
        now: datetime,
    ) -> dict[UUID, dict[str, Any]]: ...
    async def get_latest_pending_consultation_material_intent(
        self, owner_account_id: UUID, session_id: UUID, now: datetime
    ) -> dict[str, Any] | None: ...
    async def confirm_consultation_material_intent(
        self,
        owner_account_id: UUID,
        session_id: UUID,
        intent_id: UUID,
        job_expires_at: datetime,
        model_name: str,
        release_lane: str,
        user_daily_limit: int,
        user_active_limit: int,
        global_daily_limit: int,
        global_queue_limit: int,
    ) -> dict[str, Any]: ...
    async def get_application_case_authorized(self, application_id: UUID, actor_id: UUID, role: Role, department_id: UUID | None = None) -> dict[str, Any]: ...
    async def get_application_view_authorized(self, application_id: UUID, actor_id: UUID, role: Role, department_id: UUID | None = None) -> dict[str, Any]: ...
    async def create_application(self, actor_id: UUID, service_id: UUID, form_data: dict[str, Any]) -> dict[str, Any]: ...
    async def list_applications(self, principal_id: UUID, role: Role, department_id: UUID | None) -> list[dict[str, Any]]: ...
    async def update_application_form(self, application_id: UUID, actor_id: UUID, data: dict[str, Any], expected_version: int) -> dict[str, Any]: ...
    async def preflight_material_upload(self, application_id: UUID, actor_id: UUID, requirement_code: str, content_type: str) -> None: ...
    async def add_material(
        self, application_id: UUID, actor_id: UUID, requirement_code: str,
        original_name: str, object_key: str, content_type: str,
        size_bytes: int, digest: str,
    ) -> dict[str, Any]: ...
    async def get_material_authorized(self, application_id: UUID, material_id: UUID, actor_id: UUID, role: Role, department_id: UUID | None) -> dict[str, Any]: ...
    async def application_submission_context(self, application_id: UUID, actor_id: UUID) -> tuple[Any, dict[str, Any], set[str], list[Any], bool]: ...
    async def submit_application(self, application_id: UUID, actor_id: UUID, expected_version: int) -> dict[str, Any]: ...
    async def transition_application(self, application_id: UUID, actor_id: UUID, role: Role, target: ApplicationStatus, expected_version: int, comment: str | None = None, require_assignee: bool = False) -> dict[str, Any]: ...
    async def list_timeline(self, application_id: UUID, actor_id: UUID, role: Role, department_id: UUID | None) -> list[dict[str, Any]]: ...
    async def list_staff_tasks(self, account_id: UUID, department_id: UUID | None) -> list[dict[str, Any]]: ...
    async def get_review_task_department(self, task_id: UUID) -> UUID: ...
    async def get_application_review_department(self, application_id: UUID) -> UUID: ...
    async def claim_task(self, task_id: UUID, actor_id: UUID, department_id: UUID | None) -> dict[str, Any]: ...
    async def application_requires_payment(self, application_id: UUID) -> bool: ...
    async def list_consultations(self, account_id: UUID) -> list[dict[str, Any]]: ...
    async def create_feedback(self, account_id: UUID, session_id: UUID, rating: int, comment: str | None) -> dict[str, Any]: ...
    async def create_handoff(self, account_id: UUID, session_id: UUID, subject: str, department_id: UUID | None) -> dict[str, Any]: ...
    async def list_handoffs(self, actor_id: UUID, role: Role, department_id: UUID | None) -> list[dict[str, Any]]: ...
    async def add_handoff_message(self, actor_id: UUID, role: Role, department_id: UUID | None, ticket_id: UUID, content: str) -> dict[str, Any]: ...
    async def list_handoff_messages(self, actor_id: UUID, role: Role, department_id: UUID | None, ticket_id: UUID) -> list[dict[str, Any]]: ...
    async def resolve_handoff(self, actor_id: UUID, department_id: UUID | None, ticket_id: UUID) -> dict[str, Any]: ...
    async def cancel_handoff(self, actor_id: UUID, ticket_id: UUID) -> dict[str, Any]: ...
    async def create_appointment(self, account_id: UUID, service_id: UUID, window_id: UUID, slot_start: datetime) -> dict[str, Any]: ...
    async def list_appointments(self, account_id: UUID) -> list[dict[str, Any]]: ...
    async def cancel_appointment(self, account_id: UUID, appointment_id: UUID) -> dict[str, Any]: ...
    async def advance_appointment(self, actor_id: UUID, role: Role, department_id: UUID | None, appointment_id: UUID, target: AppointmentStatus) -> dict[str, Any]: ...
    async def create_payment(self, account_id: UUID, application_id: UUID) -> dict[str, Any]: ...
    async def cancel_payment(self, payment_id: UUID, account_id: UUID) -> dict[str, Any]: ...
    async def mark_payment_pending(self, payment_id: UUID, account_id: UUID) -> dict[str, Any]: ...
    async def update_payment(self, payment_id: UUID, account_id: UUID, outcome: str, provider_reference: str) -> dict[str, Any]: ...
    async def create_verification(self, account_id: UUID, application_id: UUID, expires_at: datetime) -> dict[str, Any]: ...
    async def complete_verification(self, account_id: UUID, verification_id: UUID, outcome: str) -> dict[str, Any]: ...
    async def preflight_delivery(self, account_id: UUID, application_id: UUID) -> dict[str, Any] | None: ...
    async def create_delivery(self, account_id: UUID, application_id: UUID, masked_recipient: str, masked_address: str, provider_reference: str) -> dict[str, Any]: ...
    async def advance_delivery(self, actor_id: UUID, role: Role, department_id: UUID | None, delivery_id: UUID, target: DeliveryStatus) -> dict[str, Any]: ...
    async def cancel_delivery(self, account_id: UUID, delivery_id: UUID) -> dict[str, Any]: ...
    async def create_knowledge_records(
        self, actor_id: UUID, document_id: str, title: str, source: str,
        content: str, object_key: str, chunks: list[str],
    ) -> tuple[UUID, list[dict[str, Any]], bool, str]: ...
    async def finish_knowledge_job(self, job_id: UUID, success: bool, error: str | None = None) -> None: ...
    async def list_active_knowledge_chunks(self) -> list[dict[str, str]]: ...
    async def recover_stale_knowledge_jobs(self, age_seconds: int | None = None) -> int: ...
    async def prepare_knowledge_retry(self, actor_id: UUID, job_id: UUID) -> list[dict[str, Any]]: ...
    async def archive_knowledge(self, actor_id: UUID, job_id: UUID) -> dict[str, Any]: ...
    async def create_digital_human_intent(
        self,
        owner_account_id: UUID | None,
        owner_role: Role | None,
        client_session_id: UUID,
        provider_session_id_hash: str,
        intent_type: str,
        label: str,
        section: str,
        prefill: dict[str, Any],
        expires_at: datetime,
    ) -> dict[str, Any]: ...
    async def consume_digital_human_intent(
        self,
        intent_id: UUID,
        actor_id: UUID | None,
        actor_role: Role | None,
        client_session_id: UUID,
        client_chat_id_hash: str,
        now: datetime,
        required_intent_type: str | None = None,
    ) -> dict[str, Any]: ...


class ObjectStorePort(Protocol):
    materials_bucket: str
    knowledge_bucket: str
    material_templates_bucket: str
    generated_documents_bucket: str

    async def ensure_buckets(self) -> None: ...
    async def ping(self) -> None: ...
    async def put_bytes(self, bucket: str, object_key: str, content: bytes, content_type: str) -> None: ...
    async def get_bytes(self, bucket: str, object_key: str) -> bytes: ...
    async def delete(self, bucket: str, object_key: str) -> None: ...


class SmsProviderPort(Protocol):
    async def send_code(self, destination: str, purpose: str) -> dict[str, object]: ...


class PaymentProviderPort(Protocol):
    async def pay(self, outcome: str) -> dict[str, object]: ...


class VerificationProviderPort(Protocol):
    async def verify(self, outcome: str) -> dict[str, object]: ...


class DeliveryProviderPort(Protocol):
    async def create(self) -> dict[str, object]: ...


class VectorIndexPort(Protocol):
    async def index_chunks(self, chunks: list[dict[str, str]]) -> None: ...
    async def activate_chunks(self, chunks: list[dict[str, str]]) -> None: ...
    async def delete_chunks(self, chunk_ids: list[str]) -> None: ...


class ChatPersistencePort(Protocol):
    async def save_user_message(
        self,
        session_id: UUID,
        request_id: UUID,
        message: str,
        owner_account_id: UUID | None = None,
    ) -> UUID | None: ...

    async def save_assistant_result(
        self,
        session_id: UUID,
        request_id: UUID,
        answer: str,
        sources: list[SourceData],
        tool_calls: list[ToolCallData],
        cache_hit: bool,
        warnings: list[str],
        ui_cards: list[ChatUiCardData] | None = None,
    ) -> UUID | None: ...

    async def load_recent_history(
        self,
        session_id: UUID,
        owner_account_id: UUID | None,
        limit: int = 8,
    ) -> tuple[ConversationMessageData, ...]: ...

    async def list_messages_authorized(
        self,
        session_id: UUID,
        owner_account_id: UUID,
        *,
        before: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, Any]: ...


class PublicRetrievalCachePort(Protocol):
    async def get(
        self, message: str, public_context_id: str | int | None = None
    ) -> tuple[list[SourceData], list[ToolCallData]] | None: ...

    async def set(
        self,
        message: str,
        sources: list[SourceData],
        tool_calls: list[ToolCallData],
        public_context_id: str | int | None = None,
    ) -> None: ...

    async def invalidate_public(self) -> None: ...


class GovernmentToolRetrievalPort(Protocol):
    async def retrieve(
        self,
        query: str,
        selected_service_id: int | None = None,
        allow_inferred_details: bool = True,
    ) -> tuple[list[SourceData], list[ToolCallData], list[str]]: ...


class KnowledgeRetrievalPort(Protocol):
    async def search(self, query: str, limit: int = 3) -> list[SourceData]: ...


class ChatModelPort(Protocol):
    async def answer(
        self,
        question: str,
        sources: list[SourceData],
        tool_calls: list[ToolCallData],
        request_id: UUID,
    ) -> str: ...
    def answer_stream(
        self,
        question: str,
        sources: list[SourceData],
        tool_calls: list[ToolCallData],
        request_id: UUID,
    ) -> AsyncIterator[str]: ...


class MetaStudioOnceCodePort(Protocol):
    async def create_once_code(self, app_user_id: str) -> str: ...


class MetaStudioSessionPort(Protocol):
    async def put(self, session_id: UUID, values: dict[str, Any], ttl_seconds: int) -> None: ...
    async def get(self, session_id: UUID) -> dict[str, Any] | None: ...
    async def claim_replay(self, replay_key: str, ttl_seconds: int) -> bool: ...


class VisionTicketPort(Protocol):
    async def issue(
        self, claims: VisionTicketClaimsData, ttl_seconds: int
    ) -> str: ...

    async def consume(self, token: str) -> VisionTicketClaimsData | None: ...


@dataclass(frozen=True, slots=True)
class VisionEventData:
    """Provider-neutral fact emitted by a fast, single-frame vision stage.

    The event deliberately contains no image bytes. ``attributes`` is a tuple
    rather than an arbitrary mapping so timeline entries stay immutable,
    bounded, and straightforward to validate at adapter boundaries.
    """

    kind: Literal["quality", "object", "track", "action", "ocr"]
    label: str
    confidence: float
    frame_sequence: int
    observed_at_ms: int
    track_id: str | None = None
    attributes: tuple[tuple[str, str], ...] = ()


class VisionFastAnalyzerPort(Protocol):
    async def analyze_frame(
        self, frame: VisionFrameData
    ) -> tuple[VisionEventData, ...]: ...


class VisionFrameStorePort(Protocol):
    async def cleanup_expired(self) -> None: ...

    async def register_session(
        self, client_session_id: UUID, vision_session_id: UUID
    ) -> bool: ...

    async def put(self, frame: VisionFrameData) -> str: ...

    async def append_events(
        self, frame: VisionFrameData, events: tuple[VisionEventData, ...]
    ) -> None: ...

    async def timeline_context(
        self,
        client_session_id: UUID,
        vision_session_id: UUID,
        turn_sequence: int,
        frame_count: int,
    ) -> VisualContextData | None: ...

    async def remember_late_context(
        self, context: VisualContextData, ttl_seconds: int
    ) -> None: ...

    async def pop_late_context(
        self, client_session_id: UUID
    ) -> VisualContextData | None: ...

    async def pop_latest_turn(
        self,
        client_session_id: UUID,
        expected_vision_session_id: UUID | None = None,
    ) -> VisionTurnSnapshotData: ...

    async def start_turn(
        self,
        client_session_id: UUID,
        vision_session_id: UUID,
        turn_sequence: int,
    ) -> bool: ...

    async def end_turn(
        self,
        client_session_id: UUID,
        vision_session_id: UUID,
        turn_sequence: int,
    ) -> bool: ...

    async def discard_session(
        self,
        client_session_id: UUID,
        vision_session_id: UUID,
        *,
        mark_unavailable: bool = False,
    ) -> None: ...

    async def invalidate_session(
        self, client_session_id: UUID, vision_session_id: UUID
    ) -> None: ...


class VisionAnalyzerPort(Protocol):
    async def analyze(
        self, sanitized_question: str, frames: tuple[VisionFrameData, ...]
    ) -> VisualContextData: ...

    async def analyze_document(
        self, frame: DocumentFrameData
    ) -> DocumentContextData: ...


class VisionAnalysisQuotaPort(Protocol):
    """Global spend guard checked immediately before a real VLM request."""

    async def consume(self) -> bool: ...


class KnowledgeVectorPort(VectorIndexPort, KnowledgeRetrievalPort, Protocol):
    """Combined search/index capability implemented by the Milvus adapter."""

    pass


class TokenValidationError(ValueError):
    pass


class SecurityPort(Protocol):
    def hash_password(self, password: str) -> str: ...
    def verify_password(self, password: str, encoded: str) -> bool: ...
    def issue_access_token(self, principal: Principal) -> tuple[str, datetime]: ...
    def decode_access_token(self, token: str) -> dict[str, Any]: ...
    def new_refresh_token(self) -> str: ...
    def mask_personal_text(self, value: str) -> str: ...
    def redact_public_text(self, value: str) -> str: ...


class KnowledgeParserPort(Protocol):
    def extract(self, extension: str, content: bytes) -> str: ...


class EmbeddingPort(Protocol):
    model_name: str
    dimension: int

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class CorpusArchiveReaderPort(Protocol):
    def read(
        self,
        archive_path: str,
        *,
        expected_sha256: str | None = None,
        expected_chunk_count: int = 15_858,
    ) -> CorpusArchiveData: ...


class CorpusRepositoryPort(Protocol):
    async def ensure_dataset(
        self, spec: CorpusDatasetSpec, archive: CorpusArchiveData
    ) -> CorpusDatasetState: ...

    async def pending_chunks(
        self, dataset_id: UUID, limit: int
    ) -> list[CorpusChunkData]: ...

    async def cached_embeddings(
        self, content_hashes: list[str], model: str, dimension: int
    ) -> dict[str, list[float]]: ...

    async def store_embeddings(
        self,
        embeddings: dict[str, list[float]],
        model: str,
        dimension: int,
    ) -> None: ...

    async def mark_chunks_indexed(
        self, dataset_id: UUID, external_ids: list[str]
    ) -> None: ...

    async def mark_dataset_active(
        self, dataset_id: UUID, indexed_chunk_count: int
    ) -> None: ...

    async def mark_dataset_failed(
        self, dataset_id: UUID, error_code: str
    ) -> None: ...


class VersionedCorpusIndexPort(Protocol):
    async def ensure_collections(self, spec: CorpusDatasetSpec) -> None: ...

    async def upsert_chunks(
        self,
        spec: CorpusDatasetSpec,
        chunks: list[CorpusChunkData],
        vectors: list[list[float]],
    ) -> None: ...

    async def upsert_routes(
        self,
        spec: CorpusDatasetSpec,
        routes: list[CorpusRouteData],
        vectors: list[list[float]],
    ) -> None: ...

    async def count_chunks(self, spec: CorpusDatasetSpec) -> int: ...

    async def count_routes(self, spec: CorpusDatasetSpec) -> int: ...

    async def activate_aliases(self, spec: CorpusDatasetSpec) -> None: ...


class CorpusSearchPort(Protocol):
    dataset_version: str

    async def search(self, query: str, limit: int = 6) -> list[SourceData]: ...
