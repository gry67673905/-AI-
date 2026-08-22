"""add knowledge indexing and immutable business audit records

Revision ID: 0004_knowledge_audit
Revises: 0003_applications_operations
Create Date: 2026-08-21
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_knowledge_audit"
down_revision: str | None = "0003_applications_operations"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("metadata", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("status", sa.String(24), server_default="DRAFT", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("content_hash"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_table(
        "knowledge_index_jobs",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), server_default="DRAFT", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False), sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_index_jobs_document_id", "knowledge_index_jobs", ["document_id"])
    op.create_index("ix_knowledge_index_jobs_status", "knowledge_index_jobs", ["status"])
    op.create_table(
        "business_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False), sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column("detail", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    for column in ("actor_id", "action", "resource_type", "resource_id"):
        op.create_index(f"ix_business_audit_events_{column}", "business_audit_events", [column])


def downgrade() -> None:
    op.drop_table("business_audit_events")
    op.drop_table("knowledge_index_jobs")
    op.drop_table("knowledge_chunks")
