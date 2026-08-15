"""refresh sessions add device_id and revoke_reason columns

Revision ID: 0036_refresh_sessions_cols
Revises: 0035_rename_refresh_tokens_table
Create Date: 2026-03-31 00:03:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0036_refresh_sessions_cols"
down_revision = "0035_rename_refresh_tokens_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "refresh_sessions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("refresh_sessions")}
    if "device_id" not in columns:
        op.add_column(
            "refresh_sessions",
            sa.Column("device_id", sa.String(), nullable=True),
        )
    if "revoke_reason" not in columns:
        op.add_column(
            "refresh_sessions",
            sa.Column("revoke_reason", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "refresh_sessions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("refresh_sessions")}
    if "revoke_reason" in columns:
        op.drop_column("refresh_sessions", "revoke_reason")
    if "device_id" in columns:
        op.drop_column("refresh_sessions", "device_id")
