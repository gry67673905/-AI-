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
    __table_args__ = (
        CheckConstraint(
            "coordinate_type IN ('GCJ02')",
            name="ck_service_windows_coordinate_type",
        ),
        CheckConstraint(
            "data_mode IN ('DEMO', 'VERIFIED')",
            name="ck_service_windows_data_mode",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[float] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float] = mapped_column(Numeric(10, 7))
    city_code: Mapped[str] = mapped_column(String(32), default="DEMO")
    coordinate_type: Mapped[str] = mapped_column(String(16), default="GCJ02")
    data_mode: Mapped[str] = mapped_column(String(16), default="DEMO")
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
        CheckConstraint(
            "handling_mode IN ('ONLINE_ONLY', 'OFFLINE_ONLY', 'BOTH', 'UNKNOWN')",
            name="ck_government_services_handling_mode",
        ),
        CheckConstraint(
            "online_status IN ('AVAILABLE', 'TEMP_UNAVAILABLE', 'UNKNOWN')",
            name="ck_government_services_online_status",
        ),
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
    handling_mode: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    online_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    status_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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


class ServiceWindowLinkRecord(Base, TimestampMixin):
    __tablename__ = "service_window_links"
    __table_args__ = (
        CheckConstraint(
            "priority >= 0 AND priority <= 1000",
            name="ck_service_window_links_priority",
        ),
        Index(
            "ix_service_window_links_active_priority",
            "service_id",
            "active",
            "priority",
        ),
    )

    service_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("government_services.id", ondelete="CASCADE"),
        primary_key=True,
    )
    window_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("service_windows.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


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


class MaterialTemplateRecord(Base, TimestampMixin):
    __tablename__ = "material_templates"
    __table_args__ = (
        UniqueConstraint(
            "template_key",
            "material_requirement_id",
            name="uq_material_templates_key_requirement",
        ),
        CheckConstraint(
            "mode IN ('SOURCE_EDITABLE', 'VISUAL_RECONSTRUCT', 'NOT_GENERATABLE')",
            name="ck_material_templates_mode",
        ),
        Index(
            "ix_material_templates_requirement_active",
            "material_requirement_id",
            "active",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    material_requirement_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("material_requirements.id", ondelete="CASCADE"),
        index=True,
    )
    template_key: Mapped[str] = mapped_column(String(96))
    service_code: Mapped[str] = mapped_column(String(64), index=True)
    requirement_code: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    source_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    allowed_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    notice: Mapped[str] = mapped_column(
        String(500),
        default="演示模板，仅供项目填写演示，不作为正式政务表格。",
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ConsultationMaterialIntentRecord(Base, TimestampMixin):
    __tablename__ = "consultation_material_intents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED')",
            name="ck_consultation_material_intents_status",
        ),
        Index(
            "ix_consultation_material_intents_owner_session_status",
            "owner_account_id",
            "session_id",
            "status",
        ),
        Index("ix_consultation_material_intents_expires", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="RESTRICT"), index=True
    )
    service_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("government_services.id", ondelete="RESTRICT"),
        index=True,
    )
    service_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_versions.id", ondelete="RESTRICT")
    )
    material_requirement_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_requirements.id", ondelete="RESTRICT")
    )
    template_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_templates.id", ondelete="RESTRICT")
    )
    requirement_code: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MaterialDocumentJobRecord(Base, TimestampMixin):
    __tablename__ = "material_document_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'READY', 'FAILED', 'EXPIRED')",
            name="ck_material_document_jobs_status",
        ),
        CheckConstraint(
            "template_mode_snapshot IN ('SOURCE_EDITABLE', 'VISUAL_RECONSTRUCT')",
            name="ck_material_document_jobs_template_mode_snapshot",
        ),
        CheckConstraint(
            "scope IN ('APPLICATION', 'CONSULTATION')",
            name="ck_material_document_jobs_scope",
        ),
        CheckConstraint(
            "(scope = 'APPLICATION' AND application_id IS NOT NULL "
            "AND application_version IS NOT NULL AND consultation_session_id IS NULL "
            "AND consultation_intent_id IS NULL) OR "
            "(scope = 'CONSULTATION' AND application_id IS NULL "
            "AND application_version IS NULL AND consultation_session_id IS NOT NULL "
            "AND consultation_intent_id IS NOT NULL)",
            name="ck_material_document_jobs_context",
        ),
        Index(
            "ix_material_document_jobs_lease",
            "release_lane",
            "status",
            "leased_until",
            "created_at",
        ),
        Index(
            "ix_material_document_jobs_owner_created",
            "owner_account_id",
            "created_at",
        ),
        Index(
            "ix_material_document_jobs_owner_status_created",
            "owner_account_id",
            "status",
            "created_at",
        ),
        Index("ix_material_document_jobs_expires", "expires_at"),
        UniqueConstraint(
            "consultation_intent_id",
            name="uq_material_document_jobs_consultation_intent",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(16), default="APPLICATION", index=True)
    service_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("government_services.id", ondelete="RESTRICT"),
        index=True,
    )
    service_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_versions.id", ondelete="RESTRICT")
    )
    application_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    consultation_session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )
    consultation_intent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("consultation_material_intents.id", ondelete="RESTRICT"),
        nullable=True,
    )
    material_requirement_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_requirements.id", ondelete="RESTRICT")
    )
    template_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_templates.id", ondelete="RESTRICT")
    )
    requirement_code: Mapped[str] = mapped_column(String(64))
    application_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_key_snapshot: Mapped[str] = mapped_column(String(96))
    template_version_snapshot: Mapped[int] = mapped_column(Integer)
    template_title_snapshot: Mapped[str] = mapped_column(String(200))
    template_mode_snapshot: Mapped[str] = mapped_column(String(32))
    allowed_fields_snapshot: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_object_key_snapshot: Mapped[str] = mapped_column(String(500))
    source_sha256_snapshot: Mapped[str] = mapped_column(String(64))
    model_name_snapshot: Mapped[str] = mapped_column(String(128))
    release_lane: Mapped[str] = mapped_column(String(128), default="legacy", index=True)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    form_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    request_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True, unique=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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


class DigitalHumanActionIntentRecord(Base):
    __tablename__ = "digital_human_action_intents"
    __table_args__ = (
        Index("ix_digital_human_intents_owner_status", "owner_account_id", "status"),
        Index("ix_digital_human_intents_session", "client_session_id"),
        CheckConstraint(
            "status IN ('ACTIVE', 'CONSUMED')",
            name="ck_digital_human_intent_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_account_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    client_session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    chat_id_hash: Mapped[str] = mapped_column(String(64))
    intent_type: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(100))
    section: Mapped[str] = mapped_column(String(64))
    prefill_json: Mapped[dict[str, Any]] = mapped_column("prefill", JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
