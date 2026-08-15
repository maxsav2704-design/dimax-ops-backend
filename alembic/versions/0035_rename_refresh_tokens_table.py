"""rename auth_refresh_tokens to refresh_sessions

Revision ID: 0035_rename_refresh_tokens_table
Revises: 0034_installer_profiles_table
Create Date: 2026-03-31 00:02:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0035_rename_refresh_tokens_table"
down_revision = "0034_installer_profiles_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "refresh_sessions" in tables:
        return
    if "auth_refresh_tokens" not in tables:
        return

    indexes = {index["name"] for index in inspector.get_indexes("auth_refresh_tokens")}
    constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("auth_refresh_tokens")
    }

    op.rename_table("auth_refresh_tokens", "refresh_sessions")
    if "ix_auth_refresh_tokens_user" in indexes:
        op.execute(
            "ALTER INDEX ix_auth_refresh_tokens_user RENAME TO ix_refresh_sessions_user"
        )
    if "uq_auth_refresh_tokens_company_jti" in constraints:
        op.execute(
            "ALTER TABLE refresh_sessions RENAME CONSTRAINT "
            "uq_auth_refresh_tokens_company_jti TO uq_refresh_sessions_company_jti"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "auth_refresh_tokens" in tables:
        return
    if "refresh_sessions" not in tables:
        return

    indexes = {index["name"] for index in inspector.get_indexes("refresh_sessions")}
    constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("refresh_sessions")
    }
    if "uq_refresh_sessions_company_jti" in constraints:
        op.execute(
            "ALTER TABLE refresh_sessions RENAME CONSTRAINT "
            "uq_refresh_sessions_company_jti TO uq_auth_refresh_tokens_company_jti"
        )
    if "ix_refresh_sessions_user" in indexes:
        op.execute(
            "ALTER INDEX ix_refresh_sessions_user RENAME TO ix_auth_refresh_tokens_user"
        )
    op.rename_table("refresh_sessions", "auth_refresh_tokens")
