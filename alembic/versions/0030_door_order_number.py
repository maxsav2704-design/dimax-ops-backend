"""Add order_number field to doors.

Revision ID: 0030_door_order_number
Revises: 0029_rate_effective_from
Create Date: 2026-02-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_door_order_number"
down_revision = "0029_rate_effective_from"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "doors",
        sa.Column("order_number", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("doors", "order_number")
