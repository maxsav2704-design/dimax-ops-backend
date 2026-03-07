"""Add structured layout fields to doors for project imports.

Revision ID: 0023_doors_layout_fields
Revises: 0022_installer_rates_drop_dup
Create Date: 2026-02-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_doors_layout_fields"
down_revision = "0022_installer_rates_drop_dup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("doors", sa.Column("house_number", sa.String(length=40), nullable=True))
    op.add_column("doors", sa.Column("floor_label", sa.String(length=40), nullable=True))
    op.add_column("doors", sa.Column("apartment_number", sa.String(length=40), nullable=True))
    op.add_column("doors", sa.Column("location_code", sa.String(length=80), nullable=True))
    op.add_column("doors", sa.Column("door_marking", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("doors", "door_marking")
    op.drop_column("doors", "location_code")
    op.drop_column("doors", "apartment_number")
    op.drop_column("doors", "floor_label")
    op.drop_column("doors", "house_number")
