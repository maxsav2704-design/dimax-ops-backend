"""Drop duplicate unique index on installer_rates; keep UNIQUE CONSTRAINT from 0001.

Revision ID: 0022_installer_rates_drop_dup
Revises: 0021_installer_rates_unique
Create Date: 2026-02-14

0021 added index uq_installer_rates_company_installer_door_type; 0001 already has
constraint uq_rates_installer_door_type on (company_id, installer_id, door_type_id).
One uniqueness is enough — keep the constraint, drop the redundant index.
"""
from __future__ import annotations

from alembic import op

revision = "0022_installer_rates_drop_dup"
down_revision = "0021_installer_rates_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_installer_rates_company_installer_door_type")


def downgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_installer_rates_company_installer_door_type "
        "ON public.installer_rates (company_id, installer_id, door_type_id)"
    )
