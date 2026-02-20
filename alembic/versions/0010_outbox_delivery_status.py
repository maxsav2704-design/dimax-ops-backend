"""outbox delivery status

Revision ID: 0010_outbox_delivery
Revises: 0009_outbox_provider
Create Date: 2026-02-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0010_outbox_delivery"
down_revision = "0009_outbox_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    delivery_status = postgresql.ENUM(
        "PENDING", "DELIVERED", "FAILED", name="outbox_delivery_status", create_type=False
    )
    delivery_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "outbox_messages",
        sa.Column(
            "delivery_status",
            delivery_status,
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbox_messages", "delivered_at")
    op.drop_column("outbox_messages", "delivery_status")
    postgresql.ENUM(name="outbox_delivery_status").drop(
        op.get_bind(), checkfirst=True
    )
