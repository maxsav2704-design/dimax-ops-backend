"""webhook events audit

Revision ID: 0011_webhooks
Revises: 0010_outbox_delivery
Create Date: 2026-02-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0011_webhooks"
down_revision = "0010_outbox_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_webhook_events_provider", "webhook_events", ["provider"]
    )
    op.create_index(
        "ix_webhook_events_external_id", "webhook_events", ["external_id"]
    )
    op.create_index(
        "ix_webhook_events_created_at", "webhook_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("webhook_events")
