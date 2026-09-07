"""add completed_work, door_status_history, sync_queue_items tables

Revision ID: 0037_missing_tables
Revises: 0036_refresh_sessions_cols
Create Date: 2026-03-31 00:04:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0037_missing_tables"
down_revision = "0036_refresh_sessions_cols"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "completed_work"):
        op.create_table(
            "completed_work",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("company_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "project_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "door_id",
                UUID(as_uuid=True),
                sa.ForeignKey("doors.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "installer_id",
                UUID(as_uuid=True),
                sa.ForeignKey("installers.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("quantity", sa.Numeric(12, 2), nullable=False, server_default="1.00"),
            sa.Column("rate_snapshot", sa.Numeric(12, 2), nullable=False),
            sa.Column("amount_snapshot", sa.Numeric(12, 2), nullable=False),
            sa.Column("entry_type", sa.String(20), nullable=False, server_default="ORIGINAL"),
            sa.Column(
                "correction_ref_id",
                UUID(as_uuid=True),
                sa.ForeignKey("completed_work.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "entry_type IN ('ORIGINAL', 'REVERSAL', 'CORRECTION')",
                name="ck_completed_work_entry_type",
            ),
        )
        op.create_index(
            "ix_completed_work_installer_completed_at",
            "completed_work",
            ["installer_id", "completed_at"],
        )

    if not _has_table(inspector, "door_status_history"):
        op.create_table(
            "door_status_history",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("company_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "door_id",
                UUID(as_uuid=True),
                sa.ForeignKey("doors.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "changed_by_user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("from_status", sa.String(40), nullable=True),
            sa.Column("to_status", sa.String(40), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column(
                "source",
                sa.String(40),
                nullable=False,
                server_default="SYSTEM",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_door_status_history_door_id", "door_status_history", ["door_id"]
        )

    if not _has_table(inspector, "sync_queue_items"):
        op.create_table(
            "sync_queue_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("company_id", UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), nullable=False),
            sa.Column("device_id", sa.Text(), nullable=True),
            sa.Column("entity_type", sa.String(64), nullable=False),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
            sa.Column("operation_type", sa.String(64), nullable=False),
            sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
            sa.Column("base_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("conflict_code", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.CheckConstraint(
                "status IN ('PENDING', 'APPLIED', 'CONFLICT', 'BLOCKED', 'AUTH_REQUIRED')",
                name="ck_sync_queue_items_status",
            ),
        )
        op.create_index(
            "ix_sync_queue_items_user_status",
            "sync_queue_items",
            ["user_id", "status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "sync_queue_items"):
        op.drop_index("ix_sync_queue_items_user_status", table_name="sync_queue_items")
        op.drop_table("sync_queue_items")
    if _has_table(inspector, "door_status_history"):
        op.drop_index("ix_door_status_history_door_id", table_name="door_status_history")
        op.drop_table("door_status_history")
    if _has_table(inspector, "completed_work"):
        op.drop_index(
            "ix_completed_work_installer_completed_at",
            table_name="completed_work",
        )
        op.drop_table("completed_work")
