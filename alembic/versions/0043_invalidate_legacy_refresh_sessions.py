"""Invalidate legacy non-bcrypt refresh sessions.

Revision ID: 0043_legacy_refresh_cutover
Revises: 0042_admin_profiles
Create Date: 2026-04-02 16:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0043_legacy_refresh_cutover"
down_revision = "0042_admin_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE refresh_sessions
            SET
              revoked_at = now(),
              revoke_reason = 'ADMIN_REVOKE',
              replaced_by_jti = NULL
            WHERE revoked_at IS NULL
              AND token_hash NOT LIKE '$2%';
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE refresh_sessions
            SET
              revoked_at = NULL,
              revoke_reason = NULL
            WHERE revoke_reason = 'ADMIN_REVOKE'
              AND token_hash NOT LIKE '$2%';
            """
        )
    )
