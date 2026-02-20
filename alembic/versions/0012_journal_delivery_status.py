"""journal delivery status

Revision ID: 0012_journal_delivery
Revises: 0011_webhooks
Create Date: 2026-02-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0012_journal_delivery"
down_revision = "0011_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    journal_delivery = postgresql.ENUM(
        "NONE", "PENDING", "DELIVERED", "FAILED",
        name="journal_delivery_status",
        create_type=False,
    )
    journal_delivery.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "journals",
        sa.Column(
            "email_delivery_status",
            journal_delivery,
            nullable=False,
            server_default=sa.text("'NONE'"),
        ),
    )
    op.add_column(
        "journals",
        sa.Column(
            "whatsapp_delivery_status",
            journal_delivery,
            nullable=False,
            server_default=sa.text("'NONE'"),
        ),
    )
    op.add_column(
        "journals",
        sa.Column("email_last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "journals",
        sa.Column(
            "whatsapp_last_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "journals",
        sa.Column(
            "whatsapp_delivered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "journals",
        sa.Column("email_last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "journals",
        sa.Column("whatsapp_last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("journals", "whatsapp_last_error")
    op.drop_column("journals", "email_last_error")
    op.drop_column("journals", "whatsapp_delivered_at")
    op.drop_column("journals", "whatsapp_last_sent_at")
    op.drop_column("journals", "email_last_sent_at")
    op.drop_column("journals", "whatsapp_delivery_status")
    op.drop_column("journals", "email_delivery_status")
    postgresql.ENUM(name="journal_delivery_status").drop(
        op.get_bind(), checkfirst=True
    )
