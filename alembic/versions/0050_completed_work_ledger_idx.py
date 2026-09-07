"""Add completed work indexes for admin earnings ledger.

Revision ID: 0050_completed_work_ledger_idx
Revises: 0049_product_library_items
Create Date: 2026-05-07

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0050_completed_work_ledger_idx"
down_revision = "0049_product_library_items"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if not _has_table("completed_work"):
        return

    indexes = _index_names("completed_work")
    if "ix_completed_work_company_completed_at" not in indexes:
        op.create_index(
            "ix_completed_work_company_completed_at",
            "completed_work",
            ["company_id", "completed_at", "id"],
        )
    if "ix_completed_work_company_project_completed_at" not in indexes:
        op.create_index(
            "ix_completed_work_company_project_completed_at",
            "completed_work",
            ["company_id", "project_id", "completed_at", "id"],
        )


def downgrade() -> None:
    if not _has_table("completed_work"):
        return

    indexes = _index_names("completed_work")
    if "ix_completed_work_company_project_completed_at" in indexes:
        op.drop_index(
            "ix_completed_work_company_project_completed_at",
            table_name="completed_work",
        )
    if "ix_completed_work_company_completed_at" in indexes:
        op.drop_index(
            "ix_completed_work_company_completed_at",
            table_name="completed_work",
        )
