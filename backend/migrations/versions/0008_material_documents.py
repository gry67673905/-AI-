"""add material template catalog and durable document jobs

Revision ID: 0008_material_documents
Revises: 0007_navigation_catalog
Create Date: 2026-08-26
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_material_documents"
down_revision: str | None = "0007_navigation_catalog"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "material_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_requirement_id", sa.Uuid(), nullable=False),
        sa.Column("template_key", sa.String(96), nullable=False),
        sa.Column("service_code", sa.String(64), nullable=False),
        sa.Column("requirement_code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("source_object_key", sa.String(500), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("allowed_fields", sa.JSON(), server_default="[]", nullable=False),
        sa.Column(
            "notice",
            sa.String(500),
            server_default="演示模板，仅供项目填写演示，不作为正式政务表格。",
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "mode IN ('SOURCE_EDITABLE', 'VISUAL_RECONSTRUCT', 'NOT_GENERATABLE')",
            name="ck_material_templates_mode",
        ),
        sa.ForeignKeyConstraint(
            ["material_requirement_id"], ["material_requirements.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_key",
            "material_requirement_id",
            name="uq_material_templates_key_requirement",
        ),
    )
    op.create_index("ix_material_templates_material_requirement_id", "material_templates", ["material_requirement_id"])
    op.create_index("ix_material_templates_service_code", "material_templates", ["service_code"])
    op.create_index("ix_material_templates_requirement_code", "material_templates", ["requirement_code"])
    op.create_index("ix_material_templates_active", "material_templates", ["active"])
    op.create_index(
        "ix_material_templates_requirement_active",
        "material_templates",
        ["material_requirement_id", "active"],
    )

    op.create_table(
        "material_document_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_account_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("material_requirement_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_code", sa.String(64), nullable=False),
        sa.Column("application_version", sa.Integer(), nullable=False),
        sa.Column("template_key_snapshot", sa.String(96), nullable=False),
        sa.Column("template_version_snapshot", sa.Integer(), nullable=False),
        sa.Column("template_title_snapshot", sa.String(200), nullable=False),
        sa.Column("template_mode_snapshot", sa.String(32), nullable=False),
        sa.Column("allowed_fields_snapshot", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("source_object_key_snapshot", sa.String(500), nullable=False),
        sa.Column("source_sha256_snapshot", sa.String(64), nullable=False),
        sa.Column("model_name_snapshot", sa.String(128), nullable=False),
        sa.Column("release_lane", sa.String(128), server_default="legacy", nullable=False),
        sa.Column("status", sa.String(16), server_default="QUEUED", nullable=False),
        sa.Column("form_snapshot", sa.JSON(), nullable=True),
        sa.Column("request_text", sa.Text(), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_object_key", sa.String(500), nullable=True),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("warnings", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'READY', 'FAILED', 'EXPIRED')",
            name="ck_material_document_jobs_status",
        ),
        sa.CheckConstraint(
            "template_mode_snapshot IN ('SOURCE_EDITABLE', 'VISUAL_RECONSTRUCT')",
            name="ck_material_document_jobs_template_mode_snapshot",
        ),
        sa.ForeignKeyConstraint(["owner_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["material_requirement_id"], ["material_requirements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["template_id"], ["material_templates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("output_object_key"),
    )
    op.create_index("ix_material_document_jobs_owner_account_id", "material_document_jobs", ["owner_account_id"])
    op.create_index("ix_material_document_jobs_application_id", "material_document_jobs", ["application_id"])
    op.create_index("ix_material_document_jobs_status", "material_document_jobs", ["status"])
    op.create_index("ix_material_document_jobs_release_lane", "material_document_jobs", ["release_lane"])
    op.create_index("ix_material_document_jobs_lease", "material_document_jobs", ["release_lane", "status", "leased_until", "created_at"])
    op.create_index("ix_material_document_jobs_owner_created", "material_document_jobs", ["owner_account_id", "created_at"])
    op.create_index("ix_material_document_jobs_owner_status_created", "material_document_jobs", ["owner_account_id", "status", "created_at"])
    op.create_index("ix_material_document_jobs_expires", "material_document_jobs", ["expires_at"])


def downgrade() -> None:
    op.drop_table("material_document_jobs")
    op.drop_table("material_templates")
