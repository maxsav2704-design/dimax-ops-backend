"""Create client_price_snapshots table.

Revision ID: 0045_client_price_snapshots
Revises: 0044_refresh_device_id_nn
Create Date: 2026-04-02 21:15:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0045_client_price_snapshots"
down_revision = "0044_refresh_device_id_nn"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _index_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        str(item["name"])
        for item in inspector.get_indexes(table_name)
        if item.get("name")
    }


def upgrade() -> None:
    if not _has_table("client_price_snapshots"):
        op.create_table(
            "client_price_snapshots",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("company_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "completed_work_id",
                UUID(as_uuid=True),
                sa.ForeignKey("completed_work.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("base_client_rate", sa.Numeric(12, 2), nullable=False),
            sa.Column("final_client_rate", sa.Numeric(12, 2), nullable=False),
            sa.Column("final_installer_rate", sa.Numeric(12, 2), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["company_id"],
                ["companies.id"],
                ondelete="CASCADE",
                name="fk_client_price_snapshots_company_id_companies",
            ),
            sa.UniqueConstraint(
                "completed_work_id",
                name="uq_client_price_snapshots_completed_work_id",
            ),
        )

    indexes = _index_names("client_price_snapshots")
    if "ix_client_price_snapshots_completed_work_id" not in indexes:
        op.create_index(
            "ix_client_price_snapshots_completed_work_id",
            "client_price_snapshots",
            ["completed_work_id"],
            unique=True,
        )


def downgrade() -> None:
    if not _has_table("client_price_snapshots"):
        return

    indexes = _index_names("client_price_snapshots")
    if "ix_client_price_snapshots_completed_work_id" in indexes:
        op.drop_index(
            "ix_client_price_snapshots_completed_work_id",
            table_name="client_price_snapshots",
        )
    op.drop_table("client_price_snapshots")
