"""add applications, reviews, consultations and demo operations

Revision ID: 0003_applications_operations
Revises: 0002_identity_catalog
Create Date: 2026-08-21
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_applications_operations"
down_revision: str | None = "0002_identity_catalog"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("applicant_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False), sa.Column("service_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), server_default="DRAFT", nullable=False),
        sa.Column("form_data", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True), *_timestamps(),
        sa.ForeignKeyConstraint(["applicant_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["service_id"], ["government_services.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["service_version_id"], ["service_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("applicant_id", "service_id", "status"):
        op.create_index(f"ix_applications_{column}", "applications", [column])
    op.create_table(
        "application_materials",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_code", sa.String(64), nullable=False), sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False), sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("scan_status", sa.String(32), server_default="NOT_SCANNED_DEMO", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_application_materials_application_id", "application_materials", ["application_id"])
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False), sa.Column("status", sa.String(20), server_default="PENDING", nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True), sa.Column("decision", sa.String(32), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True), *_timestamps(),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assignee_id"], ["accounts.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    for column in ("application_id", "department_id", "status"):
        op.create_index(f"ix_review_tasks_{column}", "review_tasks", [column])
    op.create_table(
        "application_events",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True), sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("from_status", sa.String(24), nullable=True), sa.Column("to_status", sa.String(24), nullable=True),
        sa.Column("detail", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_application_events_application_id", "application_events", ["application_id"])
    op.create_index("ix_application_events_event_type", "application_events", ["event_type"])
    op.create_table(
        "consultation_feedback",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False), sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consultation_feedback_session_id", "consultation_feedback", ["session_id"])
    op.create_index("ix_consultation_feedback_account_id", "consultation_feedback", ["account_id"])
    op.create_table(
        "handoff_tickets",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False), sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True), sa.Column("status", sa.String(20), server_default="QUEUED", nullable=False),
        sa.Column("subject", sa.String(200), nullable=False), *_timestamps(),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assignee_id"], ["accounts.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    for column in ("session_id", "requester_id", "status"):
        op.create_index(f"ix_handoff_tickets_{column}", "handoff_tickets", [column])
    op.create_table(
        "handoff_messages",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["handoff_tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["accounts.id"], ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_handoff_messages_ticket_id", "handoff_messages", ["ticket_id"])
    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False), sa.Column("window_id", sa.Uuid(), nullable=False),
        sa.Column("slot_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), server_default="BOOKED", nullable=False), *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["government_services.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["window_id"], ["service_windows.id"], ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"),
    )
    for column in ("account_id", "window_id", "slot_start", "status"):
        op.create_index(f"ix_appointments_{column}", "appointments", [column])
    op.create_table(
        "payment_orders",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False), sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="CREATED", nullable=False),
        sa.Column("provider_reference", sa.String(100), nullable=True), *_timestamps(),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_orders_application_id", "payment_orders", ["application_id"])
    op.create_index("ix_payment_orders_account_id", "payment_orders", ["account_id"])
    op.create_index("ix_payment_orders_status", "payment_orders", ["status"])
    op.create_table(
        "verification_sessions",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False), sa.Column("status", sa.String(20), server_default="CREATED", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("demo_notice", sa.String(255), server_default="本地模拟核验，不采集或保存真实生物信息", nullable=False), *_timestamps(),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verification_sessions_application_id", "verification_sessions", ["application_id"])
    op.create_index("ix_verification_sessions_account_id", "verification_sessions", ["account_id"])
    op.create_table(
        "delivery_orders",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False), sa.Column("status", sa.String(20), server_default="CREATED", nullable=False),
        sa.Column("masked_recipient", sa.String(120), nullable=False), sa.Column("masked_address", sa.String(255), nullable=False),
        sa.Column("provider_reference", sa.String(100), nullable=True), *_timestamps(),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("application_id"),
    )
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("preferences", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False), *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("account_id"),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(100), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_id", "scope", "idempotency_key", name="uq_idempotency_actor_scope"),
    )
    op.create_index("ix_idempotency_records_actor_id", "idempotency_records", ["actor_id"])


def downgrade() -> None:
    for table in (
        "idempotency_records", "user_preferences", "delivery_orders", "verification_sessions",
        "payment_orders", "appointments", "handoff_messages", "handoff_tickets",
        "consultation_feedback", "application_events", "review_tasks", "application_materials", "applications",
    ):
        op.drop_table(table)
