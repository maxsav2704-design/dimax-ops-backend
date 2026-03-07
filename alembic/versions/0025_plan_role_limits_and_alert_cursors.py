"""Add role-aware plan limits and alert read cursors.

Revision ID: 0025_plan_role_limits
Revises: 0024_company_plans
Create Date: 2026-02-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025_plan_role_limits"
down_revision = "0024_company_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_plans",
        sa.Column("max_admin_users", sa.Integer(), nullable=True),
    )
    op.add_column(
        "company_plans",
        sa.Column("max_installer_users", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_company_plans_max_admin_users_positive",
        "company_plans",
        "max_admin_users IS NULL OR max_admin_users > 0",
    )
    op.create_check_constraint(
        "ck_company_plans_max_installer_users_positive",
        "company_plans",
        "max_installer_users IS NULL OR max_installer_users > 0",
    )

    op.create_table(
        "audit_alert_read_cursors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "company_id",
            "user_id",
            name="uq_audit_alert_read_cursors_company_user",
        ),
    )
    op.create_index(
        "ix_audit_alert_read_cursors_company_id",
        "audit_alert_read_cursors",
        ["company_id"],
    )
    op.create_index(
        "ix_audit_alert_read_cursors_user_id",
        "audit_alert_read_cursors",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_alert_read_cursors_user_id",
        table_name="audit_alert_read_cursors",
    )
    op.drop_index(
        "ix_audit_alert_read_cursors_company_id",
        table_name="audit_alert_read_cursors",
    )
    op.drop_table("audit_alert_read_cursors")

    op.drop_constraint(
        "ck_company_plans_max_installer_users_positive",
        "company_plans",
        type_="check",
    )
    op.drop_constraint(
        "ck_company_plans_max_admin_users_positive",
        "company_plans",
        type_="check",
    )
    op.drop_column("company_plans", "max_installer_users")
    op.drop_column("company_plans", "max_admin_users")
