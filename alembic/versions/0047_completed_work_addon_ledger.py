"""Add add-on ledger fields to completed_work.

Revision ID: 0047_completed_work_addon_ledger
Revises: 0046_commercial_adjustments
Create Date: 2026-04-26 19:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0047_completed_work_addon_ledger"
down_revision = "0046_commercial_adjustments"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        str(item["name"])
        for item in inspector.get_indexes(table_name)
        if item.get("name")
    }


def _unique_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        str(item["name"])
        for item in inspector.get_unique_constraints(table_name)
        if item.get("name")
    }


def upgrade() -> None:
    if not _has_table("completed_work"):
        return

    columns = _column_names("completed_work")
    if "work_kind" not in columns:
        op.add_column(
            "completed_work",
            sa.Column(
                "work_kind",
                sa.String(20),
                nullable=False,
                server_default="DOOR",
            ),
        )
    if "addon_fact_id" not in columns:
        op.add_column(
            "completed_work",
            sa.Column("addon_fact_id", UUID(as_uuid=True), nullable=True),
        )

    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_completed_work_addon_fact_id'
          ) THEN
            ALTER TABLE completed_work
              ADD CONSTRAINT fk_completed_work_addon_fact_id
              FOREIGN KEY (addon_fact_id)
              REFERENCES project_addon_facts(id)
              ON DELETE SET NULL;
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_completed_work_work_kind'
          ) THEN
            ALTER TABLE completed_work
              ADD CONSTRAINT ck_completed_work_work_kind
              CHECK (work_kind IN ('DOOR', 'ADDON'));
          END IF;
        END $$;
        """
    )

    indexes = _index_names("completed_work")
    if "ix_completed_work_addon_fact_id" not in indexes:
        op.create_index(
            "ix_completed_work_addon_fact_id",
            "completed_work",
            ["addon_fact_id"],
        )

    uniques = _unique_names("completed_work")
    if "uq_completed_work_addon_fact_id" not in uniques:
        op.create_unique_constraint(
            "uq_completed_work_addon_fact_id",
            "completed_work",
            ["addon_fact_id"],
        )


def downgrade() -> None:
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
    if "ix_completed_work_addon_fact_id" in indexes:
        op.drop_index(
            "ix_completed_work_addon_fact_id",
            table_name="completed_work",
        )

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_completed_work_work_kind'
          ) THEN
            ALTER TABLE completed_work DROP CONSTRAINT ck_completed_work_work_kind;
          END IF;
          IF EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_completed_work_addon_fact_id'
          ) THEN
            ALTER TABLE completed_work DROP CONSTRAINT fk_completed_work_addon_fact_id;
          END IF;
        END $$;
        """
    )

    columns = _column_names("completed_work")
    if "addon_fact_id" in columns:
        op.drop_column("completed_work", "addon_fact_id")
    if "work_kind" in columns:
        op.drop_column("completed_work", "work_kind")
