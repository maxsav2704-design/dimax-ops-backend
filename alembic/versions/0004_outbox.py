"""outbox messages

Revision ID: 0004_outbox
Revises: 0003_calendar
Create Date: 2026-02-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_outbox"
down_revision = "0003_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    outbox_status = postgresql.ENUM(
        "PENDING", "SENT", "FAILED", name="outbox_status", create_type=False
    )
    outbox_channel = postgresql.ENUM("EMAIL", "WHATSAPP", name="outbox_channel", create_type=False)
    outbox_status.create(op.get_bind(), checkfirst=True)
    outbox_channel.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "outbox_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", outbox_channel, nullable=False, index=True),
        sa.Column("status", outbox_status, nullable=False, server_default=sa.text("'PENDING'"), index=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_company_id", "outbox_messages", ["company_id"])
    op.create_index("ix_outbox_status_channel", "outbox_messages", ["status", "channel"])


def downgrade() -> None:
    op.drop_table("outbox_messages")
    postgresql.ENUM("EMAIL", "WHATSAPP", name="outbox_channel").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM("PENDING", "SENT", "FAILED", name="outbox_status").drop(
        op.get_bind(), checkfirst=True
    )
