"""Prevent duplicate payroll correction entries.

Revision ID: 0057_payroll_correction_uq
Revises: 0056_financial_data_integrity
Create Date: 2026-07-31

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0057_payroll_correction_uq"
down_revision = "0056_financial_data_integrity"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_completed_work_correction_ref_entry_type"


def _index_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        index["name"]
        for index in inspector.get_indexes("completed_work")
        if index.get("name")
    }


def _assert_no_duplicate_correction_entries() -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            """
            SELECT correction_ref_id, entry_type
            FROM completed_work
            WHERE correction_ref_id IS NOT NULL
            GROUP BY correction_ref_id, entry_type
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce payroll correction uniqueness: duplicate "
            f"{duplicate.entry_type} entries reference completed work "
            f"{duplicate.correction_ref_id}"
        )


def upgrade() -> None:
    _assert_no_duplicate_correction_entries()
    if INDEX_NAME not in _index_names():
        op.create_index(
            INDEX_NAME,
            "completed_work",
            ["correction_ref_id", "entry_type"],
            unique=True,
            postgresql_where=sa.text("correction_ref_id IS NOT NULL"),
        )


def downgrade() -> None:
    if INDEX_NAME in _index_names():
        op.drop_index(INDEX_NAME, table_name="completed_work")
