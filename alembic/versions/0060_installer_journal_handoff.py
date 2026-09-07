"""Add installer-scoped journals and addon snapshots.

Revision ID: 0060_installer_journal_handoff
Revises: 0059_journal_signature_integrity
Create Date: 2026-08-29

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0060_installer_journal_handoff"
down_revision = "0059_journal_signature_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "journals",
        sa.Column("installer_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_journals_installer_id_installers",
        "journals",
        "installers",
        ["installer_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_journals_installer_id",
        "journals",
        ["installer_id"],
        unique=False,
    )

    op.create_table(
        "journal_addon_items",
        sa.Column("journal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("addon_fact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("addon_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("addon_name", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("qty_done", sa.Numeric(12, 2), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["journal_id"], ["journals.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "journal_id",
            "addon_fact_id",
            name="uq_journal_addon_items_unique",
        ),
    )
    op.create_index(
        "ix_journal_addon_items_company_id",
        "journal_addon_items",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_journal_addon_items_journal_id",
        "journal_addon_items",
        ["journal_id"],
        unique=False,
    )
    op.create_index(
        "ix_journal_addon_items_addon_fact_id",
        "journal_addon_items",
        ["addon_fact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_journal_addon_items_addon_fact_id",
        table_name="journal_addon_items",
    )
    op.drop_index(
        "ix_journal_addon_items_journal_id",
        table_name="journal_addon_items",
    )
    op.drop_index(
        "ix_journal_addon_items_company_id",
        table_name="journal_addon_items",
    )
    op.drop_table("journal_addon_items")
    op.drop_index("ix_journals_installer_id", table_name="journals")
    op.drop_constraint(
        "fk_journals_installer_id_installers",
        "journals",
        type_="foreignkey",
    )
    op.drop_column("journals", "installer_id")
