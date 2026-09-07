"""Add canonical metadata fields to refresh_sessions.

Revision ID: 0041_refresh_sessions_metadata
Revises: 0040_fix_door_status_enum
Create Date: 2026-04-02 14:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0041_refresh_sessions_metadata"
down_revision = "0040_fix_door_status_enum"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns("refresh_sessions")}


def upgrade() -> None:
    columns = _columns()

    if "issued_at" not in columns:
        op.add_column(
            "refresh_sessions",
            sa.Column(
                "issued_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )
    if "last_used_at" not in columns:
        op.add_column(
            "refresh_sessions",
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "ip_address" not in columns:
        op.add_column(
            "refresh_sessions",
            sa.Column("ip_address", sa.Text(), nullable=True),
        )
    if "user_agent" not in columns:
        op.add_column(
            "refresh_sessions",
            sa.Column("user_agent", sa.Text(), nullable=True),
        )

    op.execute(
        """
        UPDATE refresh_sessions
        SET issued_at = created_at
        WHERE issued_at IS NULL
        """
    )
    op.alter_column("refresh_sessions", "issued_at", nullable=False)


def downgrade() -> None:
    columns = _columns()

    if "user_agent" in columns:
        op.drop_column("refresh_sessions", "user_agent")
    if "ip_address" in columns:
        op.drop_column("refresh_sessions", "ip_address")
    if "last_used_at" in columns:
        op.drop_column("refresh_sessions", "last_used_at")
    if "issued_at" in columns:
        op.drop_column("refresh_sessions", "issued_at")
