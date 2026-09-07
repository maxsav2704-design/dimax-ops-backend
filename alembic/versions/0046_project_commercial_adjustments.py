"""Add project commercial adjustment tables.

Revision ID: 0046_commercial_adjustments
Revises: 0045_client_price_snapshots
Create Date: 2026-04-26 18:40:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0046_commercial_adjustments"
down_revision = "0045_client_price_snapshots"
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


def upgrade() -> None:
    if _has_table("project_addon_plans"):
        addon_plan_columns = _column_names("project_addon_plans")
        if "notes" not in addon_plan_columns:
            op.add_column(
                "project_addon_plans",
                sa.Column("notes", sa.Text(), nullable=True),
            )

    if not _has_table("project_urgency_surcharges"):
        op.create_table(
            "project_urgency_surcharges",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("company_id", UUID(as_uuid=True), nullable=False),
            sa.Column("project_id", UUID(as_uuid=True), nullable=False),
            sa.Column("scope", sa.String(20), nullable=False),
            sa.Column("order_number", sa.String(80), nullable=True),
            sa.Column("reason", sa.String(200), nullable=False),
            sa.Column("client_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("installer_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("effective_date", sa.Date(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ["company_id"],
                ["companies.id"],
                ondelete="CASCADE",
                name="fk_project_urgency_surcharges_company_id_companies",
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["projects.id"],
                ondelete="CASCADE",
                name="fk_project_urgency_surcharges_project_id_projects",
            ),
            sa.CheckConstraint(
                "scope IN ('PROJECT', 'ORDER_NUMBER')",
                name="ck_project_urgency_surcharges_scope",
            ),
            sa.CheckConstraint(
                "scope <> 'ORDER_NUMBER' OR order_number IS NOT NULL",
                name="ck_project_urgency_surcharges_order_scope",
            ),
            sa.CheckConstraint(
                "client_amount >= 0 AND installer_amount >= 0",
                name="ck_project_urgency_surcharges_amounts",
            ),
        )

    indexes = _index_names("project_urgency_surcharges")
    if "ix_project_urgency_surcharges_company_id" not in indexes:
        op.create_index(
            "ix_project_urgency_surcharges_company_id",
            "project_urgency_surcharges",
            ["company_id"],
        )
    if "ix_project_urgency_surcharges_project_id" not in indexes:
        op.create_index(
            "ix_project_urgency_surcharges_project_id",
            "project_urgency_surcharges",
            ["project_id"],
        )
    if "ix_project_urgency_surcharges_order_number" not in indexes:
        op.create_index(
            "ix_project_urgency_surcharges_order_number",
            "project_urgency_surcharges",
            ["order_number"],
        )


def downgrade() -> None:
    if _has_table("project_urgency_surcharges"):
        indexes = _index_names("project_urgency_surcharges")
        if "ix_project_urgency_surcharges_order_number" in indexes:
            op.drop_index(
                "ix_project_urgency_surcharges_order_number",
                table_name="project_urgency_surcharges",
            )
        if "ix_project_urgency_surcharges_project_id" in indexes:
            op.drop_index(
                "ix_project_urgency_surcharges_project_id",
                table_name="project_urgency_surcharges",
            )
        if "ix_project_urgency_surcharges_company_id" in indexes:
            op.drop_index(
                "ix_project_urgency_surcharges_company_id",
                table_name="project_urgency_surcharges",
            )
        op.drop_table("project_urgency_surcharges")

    if _has_table("project_addon_plans"):
        addon_plan_columns = _column_names("project_addon_plans")
        if "notes" in addon_plan_columns:
            op.drop_column("project_addon_plans", "notes")
