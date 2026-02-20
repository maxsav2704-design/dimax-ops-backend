"""outbox provider status

Revision ID: 0009_outbox_provider
Revises: 0008_file_download_events
Create Date: 2026-02-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_outbox_provider"
down_revision = "0008_file_download_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox_messages",
        sa.Column("provider_message_id", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("provider_status", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("provider_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbox_messages", "provider_error")
    op.drop_column("outbox_messages", "provider_status")
    op.drop_column("outbox_messages", "provider_message_id")
