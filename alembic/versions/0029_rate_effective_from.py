"""Add effective_from versioning for installer rates.

Revision ID: 0029_rate_effective_from
Revises: 0028_door_rate_snapshot
Create Date: 2026-02-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_rate_effective_from"
down_revision = "0028_door_rate_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "installer_rates",
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.drop_constraint(
        "uq_rates_installer_door_type",
        "installer_rates",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_rates_installer_door_type_from",
        "installer_rates",
        ["company_id", "installer_id", "door_type_id", "effective_from"],
    )
    op.create_index(
        "ix_rates_scope_effective_from",
        "installer_rates",
        ["company_id", "installer_id", "door_type_id", "effective_from"],
    )


def downgrade() -> None:
    op.drop_index("ix_rates_scope_effective_from", table_name="installer_rates")
    op.drop_constraint(
        "uq_rates_installer_door_type_from",
        "installer_rates",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_rates_installer_door_type",
        "installer_rates",
        ["company_id", "installer_id", "door_type_id"],
    )
    op.drop_column("installer_rates", "effective_from")
