"""extend sync_change_type enum

Revision ID: 0017_sync_change_type
Revises: 0016_sync_state
Create Date: 2026-02-14

"""
from __future__ import annotations

from alembic import op

revision = "0017_sync_change_type"
down_revision = "0016_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE sync_change_type ADD VALUE IF NOT EXISTS 'PROJECT_ADDON_PLAN'"
    )
    op.execute(
        "ALTER TYPE sync_change_type ADD VALUE IF NOT EXISTS 'PROJECT_ASSIGNMENTS'"
    )
    op.execute(
        "ALTER TYPE sync_change_type ADD VALUE IF NOT EXISTS 'PROJECT_BASE'"
    )
    op.execute(
        "ALTER TYPE sync_change_type ADD VALUE IF NOT EXISTS 'CATALOG_ADDON_TYPES'"
    )


def downgrade() -> None:
    pass
