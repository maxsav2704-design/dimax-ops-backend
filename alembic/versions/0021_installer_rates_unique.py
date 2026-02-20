"""installer_rates: unique (company_id, installer_id, door_type_id)

Revision ID: 0021_installer_rates_unique
Revises: 0020_installers_user_id_unique
Create Date: 2026-02-14

Ensures one rate per (installer, door_type) per company. If 0001 already
created uq_rates_installer_door_type, this adds a named index idempotently (IF NOT EXISTS).
"""
from __future__ import annotations

from alembic import op

revision = "0021_installer_rates_unique"
down_revision = "0020_installers_user_id_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_installer_rates_company_installer_door_type "
        "ON public.installer_rates (company_id, installer_id, door_type_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_installer_rates_company_installer_door_type")
