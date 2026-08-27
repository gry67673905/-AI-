"""add verified navigation catalog and service-window links

Revision ID: 0007_navigation_catalog
Revises: 0006_metastudio
Create Date: 2026-08-25
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_navigation_catalog"
down_revision: str | None = "0006_metastudio"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "government_services",
        sa.Column(
            "handling_mode",
            sa.String(20),
            server_default="UNKNOWN",
            nullable=False,
        ),
    )
    op.add_column(
        "government_services",
        sa.Column(
            "online_status",
            sa.String(24),
            server_default="UNKNOWN",
            nullable=False,
        ),
    )
    op.add_column(
        "government_services",
        sa.Column("status_reason", sa.String(255), nullable=True),
    )
    op.add_column(
        "government_services",
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_government_services_handling_mode",
        "government_services",
        "handling_mode IN ('ONLINE_ONLY', 'OFFLINE_ONLY', 'BOTH', 'UNKNOWN')",
    )
    op.create_check_constraint(
        "ck_government_services_online_status",
        "government_services",
        "online_status IN ('AVAILABLE', 'TEMP_UNAVAILABLE', 'UNKNOWN')",
    )

    op.add_column(
        "service_windows",
        sa.Column("city_code", sa.String(32), server_default="DEMO", nullable=False),
    )
    op.add_column(
        "service_windows",
        sa.Column(
            "coordinate_type",
            sa.String(16),
            server_default="GCJ02",
            nullable=False,
        ),
    )
    op.add_column(
        "service_windows",
        sa.Column(
            "data_mode", sa.String(16), server_default="DEMO", nullable=False
        ),
    )
    op.add_column(
        "service_windows",
        sa.Column("source_reference", sa.String(255), nullable=True),
    )
    op.add_column(
        "service_windows",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_service_windows_coordinate_type",
        "service_windows",
        "coordinate_type IN ('GCJ02')",
    )
    op.create_check_constraint(
        "ck_service_windows_data_mode",
        "service_windows",
        "data_mode IN ('DEMO', 'VERIFIED')",
    )

    op.create_table(
        "service_window_links",
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("window_id", sa.Uuid(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
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
            "priority >= 0 AND priority <= 1000",
            name="ck_service_window_links_priority",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["government_services.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["window_id"], ["service_windows.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("service_id", "window_id"),
    )
    op.create_index(
        "ix_service_window_links_window_id",
        "service_window_links",
        ["window_id"],
    )
    op.create_index(
        "ix_service_window_links_active_priority",
        "service_window_links",
        ["service_id", "active", "priority"],
    )

    # Preserve every legacy one-window association. The old column remains for
    # rolling compatibility; all navigation reads use this new relation.
    op.execute(
        sa.text(
            """
            INSERT INTO service_window_links
                (service_id, window_id, priority, active, created_at, updated_at)
            SELECT id, window_id, 0, TRUE, now(), now()
            FROM government_services
            WHERE window_id IS NOT NULL
            ON CONFLICT (service_id, window_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("service_window_links")
    op.drop_constraint(
        "ck_service_windows_data_mode", "service_windows", type_="check"
    )
    op.drop_constraint(
        "ck_service_windows_coordinate_type", "service_windows", type_="check"
    )
    op.drop_column("service_windows", "verified_at")
    op.drop_column("service_windows", "source_reference")
    op.drop_column("service_windows", "data_mode")
    op.drop_column("service_windows", "coordinate_type")
    op.drop_column("service_windows", "city_code")
    op.drop_constraint(
        "ck_government_services_online_status",
        "government_services",
        type_="check",
    )
    op.drop_constraint(
        "ck_government_services_handling_mode",
        "government_services",
        type_="check",
    )
    op.drop_column("government_services", "status_updated_at")
    op.drop_column("government_services", "status_reason")
    op.drop_column("government_services", "online_status")
    op.drop_column("government_services", "handling_mode")
