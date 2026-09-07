"""Fix door_status enum: add IN_PROGRESS, ISSUE_OPEN, LOCKED, CANCELLED values.

Python DoorStatus enum has 6 values since initial implementation.
PG enum was created with only INSTALLED + NOT_INSTALLED.
All 4 missing values are actively used in application code and tests.

Revision ID: 0040_fix_door_status_enum
Revises: 0038_fix_schema_core
Create Date: 2026-03-31 21:00:00
"""

from __future__ import annotations

from alembic import op


revision = "0040_fix_door_status_enum"
down_revision = "0038_fix_schema_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 12+ allows ADD VALUE inside a transaction.
    # New values cannot be used in the SAME transaction — not an issue here.
    op.execute("ALTER TYPE door_status ADD VALUE IF NOT EXISTS 'IN_PROGRESS'")
    op.execute("ALTER TYPE door_status ADD VALUE IF NOT EXISTS 'ISSUE_OPEN'")
    op.execute("ALTER TYPE door_status ADD VALUE IF NOT EXISTS 'LOCKED'")
    op.execute("ALTER TYPE door_status ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade() -> None:
    # PostgreSQL does not support DROP VALUE from an enum.
    # To reverse: recreate the type without the added values (complex, data-lossy).
    # Safe downgrade is a no-op — values simply won't be used if code is rolled back.
    pass
