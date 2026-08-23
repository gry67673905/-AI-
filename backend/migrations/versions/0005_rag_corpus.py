"""add versioned external RAG corpus and embedding checkpoint tables

Revision ID: 0005_rag_corpus
Revises: 0004_knowledge_audit
Create Date: 2026-08-22
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_rag_corpus"
down_revision: str | None = "0004_knowledge_audit"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("archive_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("source_owner", sa.String(200), nullable=True),
        sa.Column("license_status", sa.String(32), server_default="UNVERIFIED", nullable=False),
        sa.Column("status", sa.String(24), server_default="DRAFT", nullable=False),
        sa.Column("expected_chunk_count", sa.Integer(), nullable=False),
        sa.Column("imported_chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexed_chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("collection_name", sa.String(255), nullable=False),
        sa.Column("route_collection_name", sa.String(255), nullable=False),
        sa.Column("collection_alias", sa.String(255), nullable=False),
        sa.Column("route_alias", sa.String(255), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(100), nullable=True),
        sa.Column("manifest", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("expected_chunk_count > 0", name="ck_knowledge_dataset_expected_positive"),
        sa.CheckConstraint("embedding_dimension > 0", name="ck_knowledge_dataset_dimension_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("archive_sha256"),
        sa.UniqueConstraint("name", "version", name="uq_knowledge_dataset_name_version"),
    )
    op.create_index("ix_knowledge_datasets_status", "knowledge_datasets", ["status"])

    op.create_table(
        "knowledge_corpus_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("topic_slug", sa.String(16), nullable=False),
        sa.Column("topic_name", sa.String(100), nullable=False),
        sa.Column("document_title", sa.String(500), nullable=False),
        sa.Column("section", sa.String(100), nullable=False),
        sa.Column("chunk_type", sa.String(32), nullable=False),
        sa.Column("theme", sa.String(100), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_content_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), server_default="PENDING", nullable=False),
        sa.Column("metadata", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["knowledge_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "external_id", name="uq_corpus_chunk_dataset_external"),
    )
    op.create_index("ix_knowledge_corpus_chunks_dataset_id", "knowledge_corpus_chunks", ["dataset_id"])
    op.create_index("ix_knowledge_corpus_chunks_topic_slug", "knowledge_corpus_chunks", ["topic_slug"])
    op.create_index("ix_corpus_chunk_dataset_status", "knowledge_corpus_chunks", ["dataset_id", "status"])
    op.create_index("ix_corpus_chunk_content_hash", "knowledge_corpus_chunks", ["content_hash"])

    op.create_table(
        "knowledge_embedding_cache",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("vector_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("dimension > 0", name="ck_knowledge_embedding_dimension_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "content_hash", "model", "dimension",
            name="uq_knowledge_embedding_content_model_dimension",
        ),
    )
    op.create_index("ix_knowledge_embedding_cache_content_hash", "knowledge_embedding_cache", ["content_hash"])


def downgrade() -> None:
    op.drop_table("knowledge_embedding_cache")
    op.drop_table("knowledge_corpus_chunks")
    op.drop_table("knowledge_datasets")
