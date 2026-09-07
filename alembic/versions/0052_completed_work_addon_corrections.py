"""Allow add-on earnings corrections while keeping one original per fact.

Revision ID: 0052_addon_work_corrections
Revises: 0051_sync_queue_project_id
Create Date: 2026-05-11

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0052_addon_work_corrections"
down_revision = "0051_sync_queue_project_id"
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


def _unique_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
    }


def _has_duplicate_addon_originals() -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM completed_work
            WHERE addon_fact_id IS NOT NULL
              AND entry_type = 'ORIGINAL'
            GROUP BY addon_fact_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    return result is not None


def upgrade() -> None:
    if not _has_table("completed_work"):
        return

    uniques = _unique_names("completed_work")
    if "uq_completed_work_addon_fact_id" in uniques:
        op.drop_constraint(
            "uq_completed_work_addon_fact_id",
            "completed_work",
            type_="unique",
        )

    indexes = _index_names("completed_work")
    if "uq_completed_work_addon_fact_original" not in indexes:
        op.create_index(
            "uq_completed_work_addon_fact_original",
            "completed_work",
            ["addon_fact_id"],
            unique=True,
            postgresql_where=sa.text(
                "addon_fact_id IS NOT NULL AND entry_type = 'ORIGINAL'"
            ),
        )


def downgrade() -> None:
    if not _has_table("completed_work"):
        return

    indexes = _index_names("completed_work")
    if "uq_completed_work_addon_fact_original" in indexes:
        op.drop_index(
            "uq_completed_work_addon_fact_original",
            table_name="completed_work",
        )

    uniques = _unique_names("completed_work")
    if (
        "uq_completed_work_addon_fact_id" not in uniques
        and not _has_duplicate_addon_originals()
    ):
        op.create_unique_constraint(
            "uq_completed_work_addon_fact_id",
            "completed_work",
            ["addon_fact_id"],
        )
