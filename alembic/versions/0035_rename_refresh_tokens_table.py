"""rename auth_refresh_tokens to refresh_sessions

Revision ID: 0035_rename_refresh_tokens_table
Revises: 0034_installer_profiles_table
Create Date: 2026-03-31 00:02:00
"""

from __future__ import annotations

from alembic import op


revision = "0035_rename_refresh_tokens_table"
down_revision = "0034_installer_profiles_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("auth_refresh_tokens", "refresh_sessions")
    op.execute(
        "ALTER INDEX ix_auth_refresh_tokens_user RENAME TO ix_refresh_sessions_user"
    )
    op.execute(
        "ALTER TABLE refresh_sessions RENAME CONSTRAINT "
        "uq_auth_refresh_tokens_company_jti TO uq_refresh_sessions_company_jti"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE refresh_sessions RENAME CONSTRAINT "
        "uq_refresh_sessions_company_jti TO uq_auth_refresh_tokens_company_jti"
    )
    op.execute(
        "ALTER INDEX ix_refresh_sessions_user RENAME TO ix_auth_refresh_tokens_user"
    )
    op.rename_table("refresh_sessions", "auth_refresh_tokens")
