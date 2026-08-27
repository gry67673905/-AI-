"""add consultation-scoped material document generation

Revision ID: 0009_consultation_materials
Revises: 0008_material_documents
Create Date: 2026-08-27
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_consultation_materials"
down_revision: str | None = "0008_material_documents"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consultation_material_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_account_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("service_version_id", sa.Uuid(), nullable=False),
        sa.Column("material_requirement_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="PENDING", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED')",
            name="ck_consultation_material_intents_status",
        ),
        sa.ForeignKeyConstraint(
            ["owner_account_id"], ["accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["government_services.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["service_version_id"], ["service_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["material_requirement_id"],
            ["material_requirements.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["material_templates.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_consultation_material_intents_owner_account_id",
        "consultation_material_intents",
        ["owner_account_id"],
    )
    op.create_index(
        "ix_consultation_material_intents_session_id",
        "consultation_material_intents",
        ["session_id"],
    )
    op.create_index(
        "ix_consultation_material_intents_service_id",
        "consultation_material_intents",
        ["service_id"],
    )
    op.create_index(
        "ix_consultation_material_intents_status",
        "consultation_material_intents",
        ["status"],
    )
    op.create_index(
        "ix_consultation_material_intents_owner_session_status",
        "consultation_material_intents",
        ["owner_account_id", "session_id", "status"],
    )
    op.create_index(
        "ix_consultation_material_intents_expires",
        "consultation_material_intents",
        ["expires_at"],
    )

    op.add_column(
        "material_document_jobs",
        sa.Column("scope", sa.String(16), server_default="APPLICATION", nullable=False),
    )
    op.add_column(
        "material_document_jobs", sa.Column("service_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "material_document_jobs",
        sa.Column("service_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "material_document_jobs",
        sa.Column("consultation_session_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "material_document_jobs",
        sa.Column("consultation_intent_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE material_document_jobs AS jobs "
            "SET service_id = applications.service_id, "
            "service_version_id = applications.service_version_id "
            "FROM applications "
            "WHERE applications.id = jobs.application_id"
        )
    )
    op.alter_column(
        "material_document_jobs",
        "service_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.alter_column(
        "material_document_jobs",
        "service_version_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.alter_column(
        "material_document_jobs",
        "application_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.alter_column(
        "material_document_jobs",
        "application_version",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_material_document_jobs_service_id",
        "material_document_jobs",
        "government_services",
        ["service_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_material_document_jobs_service_version_id",
        "material_document_jobs",
        "service_versions",
        ["service_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_material_document_jobs_consultation_session_id",
        "material_document_jobs",
        "chat_sessions",
        ["consultation_session_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_material_document_jobs_consultation_intent_id",
        "material_document_jobs",
        "consultation_material_intents",
        ["consultation_intent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_material_document_jobs_consultation_intent",
        "material_document_jobs",
        ["consultation_intent_id"],
    )
    op.create_check_constraint(
        "ck_material_document_jobs_scope",
        "material_document_jobs",
        "scope IN ('APPLICATION', 'CONSULTATION')",
    )
    op.create_check_constraint(
        "ck_material_document_jobs_context",
        "material_document_jobs",
        "(scope = 'APPLICATION' AND application_id IS NOT NULL "
        "AND application_version IS NOT NULL AND consultation_session_id IS NULL "
        "AND consultation_intent_id IS NULL) OR "
        "(scope = 'CONSULTATION' AND application_id IS NULL "
        "AND application_version IS NULL AND consultation_session_id IS NOT NULL "
        "AND consultation_intent_id IS NOT NULL)",
    )
    op.create_index(
        "ix_material_document_jobs_scope", "material_document_jobs", ["scope"]
    )
    op.create_index(
        "ix_material_document_jobs_service_id",
        "material_document_jobs",
        ["service_id"],
    )
    op.create_index(
        "ix_material_document_jobs_consultation_session_id",
        "material_document_jobs",
        ["consultation_session_id"],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM material_document_jobs WHERE scope = 'CONSULTATION'")
    )
    op.drop_index(
        "ix_material_document_jobs_consultation_session_id",
        table_name="material_document_jobs",
    )
    op.drop_index("ix_material_document_jobs_service_id", table_name="material_document_jobs")
    op.drop_index("ix_material_document_jobs_scope", table_name="material_document_jobs")
    op.drop_constraint(
        "ck_material_document_jobs_context", "material_document_jobs", type_="check"
    )
    op.drop_constraint(
        "ck_material_document_jobs_scope", "material_document_jobs", type_="check"
    )
    op.drop_constraint(
        "uq_material_document_jobs_consultation_intent",
        "material_document_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "fk_material_document_jobs_consultation_intent_id",
        "material_document_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_material_document_jobs_consultation_session_id",
        "material_document_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_material_document_jobs_service_version_id",
        "material_document_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_material_document_jobs_service_id",
        "material_document_jobs",
        type_="foreignkey",
    )
    op.alter_column(
        "material_document_jobs",
        "application_version",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "material_document_jobs",
        "application_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_column("material_document_jobs", "consultation_intent_id")
    op.drop_column("material_document_jobs", "consultation_session_id")
    op.drop_column("material_document_jobs", "service_version_id")
    op.drop_column("material_document_jobs", "service_id")
    op.drop_column("material_document_jobs", "scope")
    op.drop_table("consultation_material_intents")
