"""Align users.email with CITEXT model type.

Revision ID: 0048_users_email_citext
Revises: 0047_completed_work_addon_ledger
Create Date: 2026-04-30 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0048_users_email_citext"
down_revision = "0047_completed_work_addon_ledger"
branch_labels = None
depends_on = None


def _index_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        str(item["name"])
        for item in inspector.get_indexes(table_name)
        if item.get("name")
    }


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    indexes = _index_names("users")
    if "ix_users_email" in indexes:
        op.drop_index("ix_users_email", table_name="users")

    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(length=255),
        type_=postgresql.CITEXT(),
        existing_nullable=False,
        postgresql_using="email::citext",
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "email",
        existing_type=postgresql.CITEXT(),
        type_=sa.String(length=255),
        existing_nullable=False,
        postgresql_using="email::varchar",
    )

    indexes = _index_names("users")
    if "ix_users_email" not in indexes:
        op.create_index("ix_users_email", "users", ["email"])
