"""sync state health fields

Revision ID: 0018_sync_state_health
Revises: 0017_sync_change_type
Create Date: 2026-02-14

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_sync_state_health"
down_revision = "0017_sync_change_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "installer_sync_state",
        sa.Column("health_status", sa.String(length=16), nullable=False, server_default="OK"),
    )
    op.add_column(
        "installer_sync_state",
        sa.Column("health_lag", sa.Integer(), nullable=True),
    )
    op.add_column(
        "installer_sync_state",
        sa.Column("health_days_offline", sa.Integer(), nullable=True),
    )
    op.add_column(
        "installer_sync_state",
        sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "installer_sync_state",
        sa.Column("last_alert_lag", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("installer_sync_state", "last_alert_lag")
    op.drop_column("installer_sync_state", "last_alert_at")
    op.drop_column("installer_sync_state", "health_days_offline")
    op.drop_column("installer_sync_state", "health_lag")
    op.drop_column("installer_sync_state", "health_status")
