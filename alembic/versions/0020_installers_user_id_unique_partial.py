"""installers.user_id unique partial index (one user -> one installer)

Revision ID: 0020_installers_user_id_unique
Revises: 0019_users_company_fk
Create Date: 2026-02-14

Verify after upgrade:
  docker compose exec db psql -U postgres -d dimax -c "\\d installers"
  # Expect: Indexes: uq_installers_user_id (UNIQUE, WHERE user_id IS NOT NULL)

  docker compose exec db psql -U postgres -d dimax -c "
  select indexname, indexdef from pg_indexes
  where tablename='installers' and indexname like '%user_id%';
  "
"""
from __future__ import annotations

from alembic import op

revision = "0020_installers_user_id_unique"
down_revision = "0019_users_company_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_installers_user_id "
        "ON public.installers (user_id) WHERE user_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_installers_user_id")
