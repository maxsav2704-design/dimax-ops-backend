"""Add project scope to installer sync queue items.

Revision ID: 0051_sync_queue_project_id
Revises: 0050_completed_work_ledger_idx
Create Date: 2026-05-11

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0051_sync_queue_project_id"
down_revision = "0050_completed_work_ledger_idx"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if not _has_table("sync_queue_items"):
        return

    columns = _column_names("sync_queue_items")
    if "project_id" not in columns:
        op.add_column(
            "sync_queue_items",
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    indexes = _index_names("sync_queue_items")
    if "ix_sync_queue_items_company_project" not in indexes:
        op.create_index(
            "ix_sync_queue_items_company_project",
            "sync_queue_items",
            ["company_id", "project_id"],
        )


def downgrade() -> None:
    if not _has_table("sync_queue_items"):
        return

    indexes = _index_names("sync_queue_items")
    if "ix_sync_queue_items_company_project" in indexes:
        op.drop_index(
            "ix_sync_queue_items_company_project",
            table_name="sync_queue_items",
        )

    columns = _column_names("sync_queue_items")
    if "project_id" in columns:
        op.drop_column("sync_queue_items", "project_id")
