"""journal tables

Revision ID: 0002_journal
Revises: 0001_initial
Create Date: 2026-02-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_journal"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    journal_status = postgresql.ENUM(
        "DRAFT", "ACTIVE", "ARCHIVED", name="journal_status", create_type=False
    )
    journal_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "journals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", journal_status, nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("public_token", sa.String(length=80), nullable=True),
        sa.Column("public_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_header", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("lock_table", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("lock_footer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signer_name", sa.String(length=200), nullable=True),
        sa.Column("snapshot_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("company_id", "public_token", name="uq_journals_company_public_token"),
    )
    op.create_index("ix_journals_company_id", "journals", ["company_id"])
    op.create_index("ix_journals_project_id", "journals", ["project_id"])
    op.create_index("ix_journals_status", "journals", ["status"])
    op.create_index("ix_journals_public_token", "journals", ["public_token"])

    op.create_table(
        "journal_door_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("journal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("door_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_label", sa.String(length=120), nullable=False),
        sa.Column("door_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["door_id"], ["doors.id"]),
        sa.UniqueConstraint("company_id", "journal_id", "door_id", name="uq_journal_door_items_unique"),
    )
    op.create_index("ix_journal_door_items_company_id", "journal_door_items", ["company_id"])
    op.create_index("ix_journal_door_items_journal_id", "journal_door_items", ["journal_id"])
    op.create_index("ix_journal_door_items_door_id", "journal_door_items", ["door_id"])

    op.create_table(
        "journal_signatures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("journal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signer_name", sa.String(length=200), nullable=False),
        sa.Column("signature_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_journal_signatures_company_id", "journal_signatures", ["company_id"])
    op.create_index("ix_journal_signatures_journal_id", "journal_signatures", ["journal_id"])

    op.create_table(
        "journal_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("journal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False, server_default=sa.text("'application/pdf'")),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("company_id", "journal_id", "kind", name="uq_journal_files_one_kind"),
    )
    op.create_index("ix_journal_files_company_id", "journal_files", ["company_id"])
    op.create_index("ix_journal_files_journal_id", "journal_files", ["journal_id"])


def downgrade() -> None:
    op.drop_table("journal_files")
    op.drop_table("journal_signatures")
    op.drop_table("journal_door_items")
    op.drop_table("journals")

    postgresql.ENUM("DRAFT", "ACTIVE", "ARCHIVED", name="journal_status").drop(
        op.get_bind(), checkfirst=True
    )
