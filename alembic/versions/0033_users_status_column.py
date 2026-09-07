"""users status column

Revision ID: 0033_users_status_column
Revises: 0032_project_contact_actions
Create Date: 2026-03-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0033_users_status_column"
down_revision = "0032_project_contact_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "status" in columns:
        return

    op.add_column(
        "users",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "status")
