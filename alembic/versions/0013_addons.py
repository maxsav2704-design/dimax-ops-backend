"""addons module

Revision ID: 0013_addons
Revises: 0012_journal_delivery
Create Date: 2026-02-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0013_addons"
down_revision = "0012_journal_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    source_enum = postgresql.ENUM("ONLINE", "OFFLINE", name="addon_fact_source", create_type=False)
    source_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "addon_types",
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
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "unit",
            sa.String(length=20),
            nullable=False,
            server_default="pcs",
        ),
        sa.Column(
            "default_client_price",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "default_installer_price",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_addon_types_company_id", "addon_types", ["company_id"])
    op.create_index("ix_addon_types_name", "addon_types", ["name"])

    op.create_table(
        "project_addon_plans",
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
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "addon_type_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "qty_planned",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "client_price",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "installer_price",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_project_addon_plans_company_id",
        "project_addon_plans",
        ["company_id"],
    )
    op.create_index(
        "ix_project_addon_plans_project_id",
        "project_addon_plans",
        ["project_id"],
    )
    op.create_unique_constraint(
        "uq_project_addon_plans_project_type",
        "project_addon_plans",
        ["company_id", "project_id", "addon_type_id"],
    )

    op.create_table(
        "project_addon_facts",
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
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "addon_type_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "installer_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("qty_done", sa.Numeric(12, 2), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "source",
            source_enum,
            nullable=False,
            server_default="ONLINE",
        ),
        sa.Column("client_event_id", sa.String(length=80), nullable=True),
    )
    op.create_index(
        "ix_project_addon_facts_company_id",
        "project_addon_facts",
        ["company_id"],
    )
    op.create_index(
        "ix_project_addon_facts_project_id",
        "project_addon_facts",
        ["project_id"],
    )
    op.create_index(
        "ix_project_addon_facts_installer_id",
        "project_addon_facts",
        ["installer_id"],
    )
    op.create_unique_constraint(
        "uq_project_addon_facts_client_event",
        "project_addon_facts",
        ["company_id", "client_event_id"],
    )


def downgrade() -> None:
    op.drop_table("project_addon_facts")
    op.drop_table("project_addon_plans")
    op.drop_table("addon_types")
    postgresql.ENUM(name="addon_fact_source").drop(
        op.get_bind(), checkfirst=True
    )
