from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.enums import (
    ApplicantType,
    AppointmentStatus,
    ApplicationStatus,
    DeliveryStatus,
    DigitalHumanIntentStatus,
    HandoffStatus,
    KnowledgeStatus,
    PaymentStatus,
    Role,
    ServiceStatus,
    VerificationStatus,
)


@dataclass(frozen=True, slots=True)
class Account:
    id: UUID
    username: str
    display_name: str
    role: Role
    applicant_type: ApplicantType | None
    active: bool
    token_version: int


@dataclass(frozen=True, slots=True)
class Department:
    id: UUID
    code: str
    name: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class ServiceWindow:
    id: UUID
    department_id: UUID
    name: str
    address: str
    latitude: float
    longitude: float
    active: bool = True


@dataclass(frozen=True, slots=True)
class ServiceVersion:
    id: UUID
    service_id: UUID
    version: int
    title: str
    summary: str
    form_schema: dict[str, Any]
    fee_cents: int
    fee_required: bool
    fee_calculation: str | None
    appointment_supported: bool
    requires_appointment: bool
    requires_verification: bool
    delivery_supported: bool
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GovernmentService:
    id: UUID
    code: str
    department_id: UUID
    applicant_type: ApplicantType
    status: ServiceStatus
    current_version_id: UUID | None


@dataclass(frozen=True, slots=True)
class MaterialRequirement:
    id: UUID
    service_version_id: UUID
    code: str
    name: str
    required: bool
    condition: dict[str, Any] | None = None
    accepted_types: tuple[str, ...] = ("application/pdf", "image/jpeg", "image/png")


@dataclass(frozen=True, slots=True)
class Application:
    id: UUID
    applicant_id: UUID
    service_id: UUID
    service_version_id: UUID
    status: ApplicationStatus
    form_data: dict[str, Any]
    version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    id: UUID
    application_id: UUID
    actor_id: UUID | None
    event_type: str
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus | None
    detail: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    outcome: str
    reasons: tuple[str, ...]
    missing_fields: tuple[str, ...]
    disclaimer: str = "资格预检仅供演示参考，不是正式审批结论。"


@dataclass(frozen=True, slots=True)
class StaffAssignment:
    id: UUID
    account_id: UUID
    department_id: UUID
    window_id: UUID | None
    active: bool


@dataclass(frozen=True, slots=True)
class EligibilityRule:
    id: UUID
    service_version_id: UUID
    rule: dict[str, Any]
    failure_message: str
    order: int


@dataclass(frozen=True, slots=True)
class ProcessStep:
    id: UUID
    service_version_id: UUID
    order: int
    code: str
    title: str
    actor: str
    description: str
    expected_duration: str


@dataclass(frozen=True, slots=True)
class FaqEntry:
    id: UUID
    service_version_id: UUID
    question: str
    answer: str


@dataclass(frozen=True, slots=True)
class PolicySource:
    id: UUID
    service_version_id: UUID
    title: str
    reference: str


@dataclass(frozen=True, slots=True)
class ApplicationMaterial:
    id: UUID
    application_id: UUID
    requirement_code: str
    original_name: str
    content_type: str
    size_bytes: int
    sha256: str
    scan_status: str


@dataclass(frozen=True, slots=True)
class ReviewTask:
    id: UUID
    application_id: UUID
    department_id: UUID
    status: str
    assignee_id: UUID | None


@dataclass(frozen=True, slots=True)
class StaffDecision:
    application_id: UUID
    reviewer_id: UUID
    decision: str
    comment: str | None
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class ConsultationSession:
    id: UUID
    owner_account_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ConsultationMessage:
    id: UUID
    session_id: UUID
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ConsultationFeedback:
    id: UUID
    session_id: UUID
    account_id: UUID
    rating: int
    comment: str | None


@dataclass(frozen=True, slots=True)
class HandoffTicket:
    id: UUID
    session_id: UUID
    requester_id: UUID
    department_id: UUID | None
    assignee_id: UUID | None
    status: HandoffStatus
    subject: str


@dataclass(frozen=True, slots=True)
class HandoffMessage:
    id: UUID
    ticket_id: UUID
    sender_id: UUID
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Appointment:
    id: UUID
    account_id: UUID
    service_id: UUID
    window_id: UUID
    slot_start: datetime
    status: AppointmentStatus


@dataclass(frozen=True, slots=True)
class PaymentOrder:
    id: UUID
    application_id: UUID
    account_id: UUID
    amount_cents: int
    status: PaymentStatus
    provider_reference: str | None


@dataclass(frozen=True, slots=True)
class VerificationSession:
    id: UUID
    application_id: UUID
    account_id: UUID
    status: VerificationStatus
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryOrder:
    id: UUID
    application_id: UUID
    account_id: UUID
    status: DeliveryStatus
    masked_recipient: str
    masked_address: str


@dataclass(frozen=True, slots=True)
class UserPreference:
    account_id: UUID
    preferences: dict[str, Any]


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    id: UUID
    document_id: str
    chunk_index: int
    content: str
    content_hash: str
    status: KnowledgeStatus


@dataclass(frozen=True, slots=True)
class KnowledgeIndexJob:
    id: UUID
    document_id: str
    status: KnowledgeStatus
    attempts: int
    last_error: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeDataset:
    id: UUID
    name: str
    version: str
    archive_sha256: str
    manifest_hash: str
    status: KnowledgeStatus
    expected_chunk_count: int
    indexed_chunk_count: int
    embedding_model: str
    embedding_dimension: int


@dataclass(frozen=True, slots=True)
class KnowledgeCorpusChunk:
    id: UUID
    dataset_id: UUID
    external_id: str
    topic_slug: str
    document_title: str
    section: str
    chunk_type: str
    content: str
    content_hash: str
    status: str


@dataclass(frozen=True, slots=True)
class BusinessAuditEvent:
    id: UUID
    actor_id: UUID | None
    action: str
    resource_type: str
    resource_id: str
    detail: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DigitalHumanActionIntent:
    """A short-lived proposal that can only navigate to a typed workbench.

    The entity deliberately contains no arbitrary URL, HTTP method or executable
    command.  A normal authenticated API call still performs every mutation.
    """

    id: UUID
    owner_account_id: UUID | None
    owner_role: Role | None
    client_session_id: UUID
    chat_id_hash: str
    intent_type: str
    label: str
    section: str
    prefill: dict[str, Any]
    status: DigitalHumanIntentStatus
    expires_at: datetime
    consumed_at: datetime | None = None
