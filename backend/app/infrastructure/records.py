from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    JSON,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DepartmentRecord(Base, TimestampMixin):
    __tablename__ = "departments"
    __table_args__ = (Index("ix_departments_code", "code"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AccountRecord(Base, TimestampMixin):
    __tablename__ = "accounts"
    __table_args__ = (Index("ix_accounts_username", "username"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(16), index=True)
    applicant_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    department_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    profile_json: Mapped[dict[str, Any]] = mapped_column("profile", JSON, default=dict)


class RefreshTokenRecord(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ServiceWindowRecord(Base, TimestampMixin):
    __tablename__ = "service_windows"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[float] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float] = mapped_column(Numeric(10, 7))
    opening_hours: Mapped[str] = mapped_column(String(120), default="工作日 09:00-17:00")
    capacity_per_slot: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class StaffAssignmentRecord(Base):
    __tablename__ = "staff_assignments"
    __table_args__ = (UniqueConstraint("account_id", "department_id", name="uq_staff_department"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), index=True
    )
    window_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_windows.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GovernmentServiceRecord(Base, TimestampMixin):
    __tablename__ = "government_services"
    __table_args__ = (
        Index("ix_government_services_code", "code"),
        Index("ix_government_services_external_item_id", "external_item_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    external_item_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    window_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_windows.id", ondelete="SET NULL"), nullable=True
    )
    applicant_type: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    current_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "service_versions.id",
            name="fk_service_current_version",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )


class ServiceVersionRecord(Base):
    __tablename__ = "service_versions"
    __table_args__ = (UniqueConstraint("service_id", "version", name="uq_service_version"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    service_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("government_services.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), index=True)
    summary: Mapped[str] = mapped_column(Text)
    form_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    fee_required: Mapped[bool] = mapped_column(Boolean, default=False)
    fee_calculation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    appointment_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_appointment: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    immutable: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EligibilityRuleRecord(Base):
    __tablename__ = "eligibility_rules"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    service_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_versions.id", ondelete="CASCADE"), index=True
    )
    rule_json: Mapped[dict[str, Any]] = mapped_column("rule", JSON)
    failure_message: Mapped[str] = mapped_column(String(255))
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class MaterialRequirementRecord(Base):
    __tablename__ = "material_requirements"
    __table_args__ = (
        UniqueConstraint("service_version_id", "code", name="uq_material_version_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    service_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_versions.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    condition_json: Mapped[dict[str, Any] | None] = mapped_column("condition", JSON, nullable=True)
    accepted_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class ProcessStepRecord(Base):
    __tablename__ = "process_steps"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    service_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_versions.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(40), default="STEP")
    title: Mapped[str] = mapped_column(String(120))
    actor: Mapped[str] = mapped_column(String(32), default="SYSTEM")
    description: Mapped[str] = mapped_column(Text)
    expected_duration: Mapped[str] = mapped_column(String(80), default="即时")


class FaqEntryRecord(Base):
    __tablename__ = "faq_entries"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    service_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_versions.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(String(255))
    answer: Mapped[str] = mapped_column(Text)


class PolicySourceRecord(Base):
    __tablename__ = "policy_sources"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    service_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_versions.id", ondelete="CASCADE",), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    reference: Mapped[str] = mapped_column(String(500))


class ApplicationRecord(Base, TimestampMixin):
    __tablename__ = "applications"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    applicant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    service_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("government_services.id", ondelete="RESTRICT"), index=True
    )
    service_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_versions.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
    form_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApplicationMaterialRecord(Base):
    __tablename__ = "application_materials"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    requirement_code: Mapped[str] = mapped_column(String(64))
    original_name: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    scan_status: Mapped[str] = mapped_column(String(32), default="NOT_SCANNED_DEMO")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewTaskRecord(Base, TimestampMixin):
    __tablename__ = "review_tasks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    assignee_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApplicationEventRecord(Base):
    __tablename__ = "application_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    detail_json: Mapped[dict[str, Any]] = mapped_column("detail", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConsultationFeedbackRecord(Base):
    __tablename__ = "consultation_feedback"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class HandoffTicketRecord(Base, TimestampMixin):
    __tablename__ = "handoff_tickets"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    requester_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    department_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    assignee_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    subject: Mapped[str] = mapped_column(String(200))


class HandoffMessageRecord(Base):
    __tablename__ = "handoff_messages"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("handoff_tickets.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AppointmentRecord(Base, TimestampMixin):
    __tablename__ = "appointments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("government_services.id", ondelete="RESTRICT")
    )
    window_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_windows.id", ondelete="RESTRICT"), index=True
    )
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="BOOKED", index=True)


class PaymentOrderRecord(Base, TimestampMixin):
    __tablename__ = "payment_orders"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="CREATED", index=True)
    provider_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)


class VerificationSessionRecord(Base, TimestampMixin):
    __tablename__ = "verification_sessions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="CREATED")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    demo_notice: Mapped[str] = mapped_column(
        String(255), default="本地模拟核验，不采集或保存真实生物信息"
    )


class DeliveryOrderRecord(Base, TimestampMixin):
    __tablename__ = "delivery_orders"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), unique=True
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(20), default="CREATED")
    masked_recipient: Mapped[str] = mapped_column(String(120))
    masked_address: Mapped[str] = mapped_column(String(255))
    provider_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)


class UserPreferenceRecord(Base, TimestampMixin):
    __tablename__ = "user_preferences"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), unique=True
    )
    preferences_json: Mapped[dict[str, Any]] = mapped_column("preferences", JSON, default=dict)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("actor_id", "scope", "idempotency_key", name="uq_idempotency_actor_scope"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[dict[str, Any]] = mapped_column("response", JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KnowledgeChunkRecord(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KnowledgeIndexJobRecord(Base, TimestampMixin):
    __tablename__ = "knowledge_index_jobs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeDatasetRecord(Base, TimestampMixin):
    __tablename__ = "knowledge_datasets"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_knowledge_dataset_name_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(64))
    archive_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    manifest_hash: Mapped[str] = mapped_column(String(64))
    source_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    license_status: Mapped[str] = mapped_column(String(32), default="UNVERIFIED")
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
    expected_chunk_count: Mapped[int] = mapped_column(Integer)
    imported_chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    collection_name: Mapped[str] = mapped_column(String(255))
    route_collection_name: Mapped[str] = mapped_column(String(255))
    collection_alias: Mapped[str] = mapped_column(String(255))
    route_alias: Mapped[str] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manifest_json: Mapped[dict[str, Any]] = mapped_column("manifest", JSON, default=dict)


class KnowledgeCorpusChunkRecord(Base):
    __tablename__ = "knowledge_corpus_chunks"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "external_id", name="uq_corpus_chunk_dataset_external"
        ),
        Index("ix_corpus_chunk_dataset_status", "dataset_id", "status"),
        Index("ix_corpus_chunk_content_hash", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_datasets.id", ondelete="CASCADE"),
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(64))
    topic_slug: Mapped[str] = mapped_column(String(16), index=True)
    topic_name: Mapped[str] = mapped_column(String(100))
    document_title: Mapped[str] = mapped_column(String(500))
    section: Mapped[str] = mapped_column(String(100))
    chunk_type: Mapped[str] = mapped_column(String(32))
    theme: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    source_content_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KnowledgeEmbeddingCacheRecord(Base):
    __tablename__ = "knowledge_embedding_cache"
    __table_args__ = (
        UniqueConstraint(
            "content_hash", "model", "dimension",
            name="uq_knowledge_embedding_content_model_dimension",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(100))
    dimension: Mapped[int] = mapped_column(Integer)
    vector_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BusinessAuditEventRecord(Base):
    __tablename__ = "business_audit_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str] = mapped_column(String(100), index=True)
    detail_json: Mapped[dict[str, Any]] = mapped_column("detail", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
