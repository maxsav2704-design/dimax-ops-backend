"""add FK users.company_id -> companies.id

Revision ID: 0019_users_company_fk
Revises: 0018_sync_state_health
Create Date: 2026-02-14

"""
from __future__ import annotations

from alembic import op

revision = "0019_users_company_fk"
down_revision = "0018_sync_state_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Удаляем старый FK с авто-именем, если есть (чистая база — нет, старая — может быть)
    try:
        op.drop_constraint(
            "users_company_id_fkey",
            "users",
            type_="foreignkey",
        )
    except Exception:
        pass

    op.create_foreign_key(
        "fk_users_company_id_companies",
        source_table="users",
        referent_table="companies",
        local_cols=["company_id"],
        remote_cols=["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_company_id_companies", "users", type_="foreignkey")
