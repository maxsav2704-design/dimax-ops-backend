"""sync cursor v2 change log

Revision ID: 0015_sync_cursor_v2
Revises: 0014_sync_events
Create Date: 2026-02-13

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015_sync_cursor_v2"
down_revision = "0014_sync_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS sync_cursor_seq START 1")

    change_type = postgresql.ENUM(
        "DOOR", "ADDON_FACT", name="sync_change_type", create_type=False
    )
    change_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "sync_change_log",
        sa.Column(
            "cursor_id",
            sa.BigInteger(),
            primary_key=True,
            nullable=False,
            server_default=sa.text("nextval('sync_cursor_seq')"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_type", change_type, nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "installer_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_sync_change_company_cursor",
        "sync_change_log",
        ["company_id", "cursor_id"],
    )
    op.create_index(
        "ix_sync_change_company_installer_cursor",
        "sync_change_log",
        ["company_id", "installer_id", "cursor_id"],
    )
    op.create_index(
        "ix_sync_change_project",
        "sync_change_log",
        ["company_id", "project_id"],
    )


def downgrade() -> None:
    op.drop_table("sync_change_log")
    postgresql.ENUM(name="sync_change_type").drop(
        op.get_bind(), checkfirst=True
    )
    op.execute("DROP SEQUENCE IF EXISTS sync_cursor_seq")
