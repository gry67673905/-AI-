"""add identity, organization and versioned service catalog

Revision ID: 0002_identity_catalog
Revises: 0001_initial
Create Date: 2026-08-21
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_identity_catalog"
down_revision: str | None = "0001_initial"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("code"),
    )
    op.create_index("ix_departments_code", "departments", ["code"])
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("applicant_type", sa.String(16), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("profile", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("username"),
    )
    op.create_index("ix_accounts_username", "accounts", ["username"])
    op.create_index("ix_accounts_role", "accounts", ["role"])
    op.create_index("ix_accounts_active", "accounts", ["active"])
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_tokens_account_id", "refresh_tokens", ["account_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])
    op.add_column("chat_sessions", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_chat_sessions_owner", "chat_sessions", "accounts", ["owner_account_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_chat_sessions_owner_account_id", "chat_sessions", ["owner_account_id"])
    op.create_table(
        "service_windows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("opening_hours", sa.String(120), server_default="工作日 09:00-17:00", nullable=False),
        sa.Column("capacity_per_slot", sa.Integer(), server_default="10", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("code"),
    )
    op.create_index("ix_service_windows_department_id", "service_windows", ["department_id"])
    op.create_table(
        "staff_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("window_id", sa.Uuid(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["window_id"], ["service_windows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("account_id", "department_id", name="uq_staff_department"),
    )
    op.create_index("ix_staff_assignments_account_id", "staff_assignments", ["account_id"])
    op.create_index("ix_staff_assignments_department_id", "staff_assignments", ["department_id"])
    op.create_table(
        "government_services",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("external_item_id", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("window_id", sa.Uuid(), nullable=True),
        sa.Column("applicant_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), server_default="DRAFT", nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["window_id"], ["service_windows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("code"), sa.UniqueConstraint("external_item_id"),
    )
    op.create_index("ix_government_services_code", "government_services", ["code"])
    op.create_index("ix_government_services_external_item_id", "government_services", ["external_item_id"])
    op.create_index("ix_government_services_department_id", "government_services", ["department_id"])
    op.create_index("ix_government_services_applicant_type", "government_services", ["applicant_type"])
    op.create_index("ix_government_services_status", "government_services", ["status"])
    op.create_table(
        "service_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("form_schema", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("fee_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fee_required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("fee_calculation", sa.String(500), nullable=True),
        sa.Column("appointment_supported", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("requires_appointment", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("requires_verification", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("delivery_supported", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("immutable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["government_services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("service_id", "version", name="uq_service_version"),
    )
    op.create_index("ix_service_versions_service_id", "service_versions", ["service_id"])
    op.create_index("ix_service_versions_title", "service_versions", ["title"])
    op.create_foreign_key(
        "fk_service_current_version", "government_services", "service_versions", ["current_version_id"], ["id"], ondelete="SET NULL"
    )
    op.create_table(
        "eligibility_rules",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("service_version_id", sa.Uuid(), nullable=False),
        sa.Column("rule", sa.JSON(), nullable=False), sa.Column("failure_message", sa.String(255), nullable=False),
        sa.Column("order_index", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["service_version_id"], ["service_versions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eligibility_rules_service_version_id", "eligibility_rules", ["service_version_id"])
    op.create_table(
        "material_requirements",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("service_version_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False), sa.Column("name", sa.String(200), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.true(), nullable=False), sa.Column("condition", sa.JSON(), nullable=True),
        sa.Column("accepted_types", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("order_index", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["service_version_id"], ["service_versions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_version_id", "code", name="uq_material_version_code"),
    )
    op.create_index("ix_material_requirements_service_version_id", "material_requirements", ["service_version_id"])
    op.create_table(
        "process_steps",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("service_version_id", sa.Uuid(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False), sa.Column("code", sa.String(40), server_default="STEP", nullable=False),
        sa.Column("title", sa.String(120), nullable=False), sa.Column("actor", sa.String(32), server_default="SYSTEM", nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("expected_duration", sa.String(80), server_default="即时", nullable=False),
        sa.ForeignKeyConstraint(["service_version_id"], ["service_versions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_process_steps_service_version_id", "process_steps", ["service_version_id"])
    op.create_table(
        "faq_entries",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("service_version_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.String(255), nullable=False), sa.Column("answer", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["service_version_id"], ["service_versions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_faq_entries_service_version_id", "faq_entries", ["service_version_id"])
    op.create_table(
        "policy_sources",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("service_version_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("reference", sa.String(500), nullable=False),
        sa.ForeignKeyConstraint(["service_version_id"], ["service_versions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_policy_sources_service_version_id", "policy_sources", ["service_version_id"])


def downgrade() -> None:
    for table in ("policy_sources", "faq_entries", "process_steps", "material_requirements", "eligibility_rules"):
        op.drop_table(table)
    op.drop_constraint("fk_service_current_version", "government_services", type_="foreignkey")
    op.drop_table("service_versions")
    op.drop_table("government_services")
    op.drop_table("staff_assignments")
    op.drop_table("service_windows")
    op.drop_index("ix_chat_sessions_owner_account_id", table_name="chat_sessions")
    op.drop_constraint("fk_chat_sessions_owner", "chat_sessions", type_="foreignkey")
    op.drop_column("chat_sessions", "owner_account_id")
    op.drop_table("refresh_tokens")
    op.drop_table("accounts")
    op.drop_table("departments")
