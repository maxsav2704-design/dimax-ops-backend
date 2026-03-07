"""Add project import runs table for idempotent file imports.

Revision ID: 0026_project_import_runs
Revises: 0025_plan_role_limits
Create Date: 2026-02-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026_project_import_runs"
down_revision = "0025_plan_role_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_import_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("import_mode", sa.String(length=16), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("mapping_profile", sa.String(length=64), nullable=False),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "company_id",
            "project_id",
            "fingerprint",
            "import_mode",
            name="uq_project_import_runs_scope_fingerprint_mode",
        ),
    )
    op.create_index(
        "ix_project_import_runs_company_id",
        "project_import_runs",
        ["company_id"],
    )
    op.create_index(
        "ix_project_import_runs_project_id",
        "project_import_runs",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_import_runs_project_id", table_name="project_import_runs")
    op.drop_index("ix_project_import_runs_company_id", table_name="project_import_runs")
    op.drop_table("project_import_runs")
