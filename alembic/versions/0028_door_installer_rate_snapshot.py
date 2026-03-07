"""Add immutable installer rate snapshot on doors.

Revision ID: 0028_door_rate_snapshot
Revises: 0027_issue_workflow_fields
Create Date: 2026-02-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_door_rate_snapshot"
down_revision = "0027_issue_workflow_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "doors",
        sa.Column("installer_rate_snapshot", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("doors", "installer_rate_snapshot")
