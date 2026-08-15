"""Harden refresh_sessions.device_id to NOT NULL.

Revision ID: 0044_refresh_device_id_nn
Revises: 0043_legacy_refresh_cutover
Create Date: 2026-04-02 16:45:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0044_refresh_device_id_nn"
down_revision = "0043_legacy_refresh_cutover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE refresh_sessions
            SET
              revoked_at = COALESCE(revoked_at, now()),
              revoke_reason = COALESCE(revoke_reason, 'ADMIN_REVOKE'),
              replaced_by_jti = NULL,
              device_id = 'revoked:' || id::text
            WHERE device_id IS NULL;
            """
        )
    )
    op.alter_column("refresh_sessions", "device_id", nullable=False)


def downgrade() -> None:
    op.alter_column("refresh_sessions", "device_id", nullable=True)
    op.execute(
        sa.text(
            """
            UPDATE refresh_sessions
            SET device_id = NULL
            WHERE revoked_at IS NOT NULL
              AND device_id LIKE 'revoked:%';
            """
        )
    )
