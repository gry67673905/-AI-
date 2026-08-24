"""add short-lived digital-human action intents

Revision ID: 0006_metastudio
Revises: 0005_rag_corpus
Create Date: 2026-08-23
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_metastudio"
down_revision: str | None = "0005_rag_corpus"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "digital_human_action_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_account_id", sa.Uuid(), nullable=True),
        sa.Column("owner_role", sa.String(16), nullable=True),
        sa.Column("client_session_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id_hash", sa.String(64), nullable=False),
        sa.Column("intent_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("section", sa.String(64), nullable=False),
        sa.Column("prefill", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("status", sa.String(16), server_default="ACTIVE", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'CONSUMED')",
            name="ck_digital_human_intent_status",
        ),
        sa.ForeignKeyConstraint(
            ["owner_account_id"], ["accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_digital_human_intents_owner_status",
        "digital_human_action_intents",
        ["owner_account_id", "status"],
    )
    op.create_index(
        "ix_digital_human_intents_session",
        "digital_human_action_intents",
        ["client_session_id"],
    )


def downgrade() -> None:
    op.drop_table("digital_human_action_intents")
