"""Add company subscription plans and limits scaffold.

Revision ID: 0024_company_plans
Revises: 0023_doors_layout_fields
Create Date: 2026-02-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024_company_plans"
down_revision = "0023_doors_layout_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_code", sa.String(length=32), nullable=False, server_default=sa.text("'trial'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("max_installers", sa.Integer(), nullable=True),
        sa.Column("max_projects", sa.Integer(), nullable=True),
        sa.Column("max_doors_per_project", sa.Integer(), nullable=True),
        sa.Column("monthly_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.CheckConstraint("max_users IS NULL OR max_users > 0", name="ck_company_plans_max_users_positive"),
        sa.CheckConstraint(
            "max_installers IS NULL OR max_installers > 0",
            name="ck_company_plans_max_installers_positive",
        ),
        sa.CheckConstraint(
            "max_projects IS NULL OR max_projects > 0",
            name="ck_company_plans_max_projects_positive",
        ),
        sa.CheckConstraint(
            "max_doors_per_project IS NULL OR max_doors_per_project > 0",
            name="ck_company_plans_max_doors_per_project_positive",
        ),
        sa.CheckConstraint(
            "monthly_price IS NULL OR monthly_price >= 0",
            name="ck_company_plans_monthly_price_nonnegative",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("company_id", name="uq_company_plans_company_id"),
    )
    op.create_index("ix_company_plans_company_id", "company_plans", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_company_plans_company_id", table_name="company_plans")
    op.drop_table("company_plans")

