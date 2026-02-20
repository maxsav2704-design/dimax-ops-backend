"""installer sync state

Revision ID: 0016_sync_state
Revises: 0015_sync_cursor_v2
Create Date: 2026-02-13

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016_sync_state"
down_revision = "0015_sync_cursor_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "installer_sync_state",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "installer_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "last_cursor_ack",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("app_version", sa.String(length=40), nullable=True),
        sa.Column("device_id", sa.String(length=80), nullable=True),
    )
    op.create_index(
        "ix_installer_sync_state_company",
        "installer_sync_state",
        ["company_id"],
    )
    op.create_unique_constraint(
        "uq_installer_sync_state_company_installer",
        "installer_sync_state",
        ["company_id", "installer_id"],
    )


def downgrade() -> None:
    op.drop_table("installer_sync_state")
