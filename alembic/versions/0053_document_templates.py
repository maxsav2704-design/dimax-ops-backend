"""Add document templates and generated project documents.

Revision ID: 0053_document_templates
Revises: 0052_addon_work_corrections
Create Date: 2026-05-18

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0053_document_templates"
down_revision = "0052_addon_work_corrections"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("document_templates"):
        op.create_table(
            "document_templates",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("code", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("entity_scope", sa.String(length=40), server_default="PROJECT", nullable=False),
            sa.Column("source_filename", sa.String(length=255), nullable=False),
            sa.Column("object_key", sa.String(length=800), nullable=False),
            sa.Column("mime_type", sa.String(length=120), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column(
                "placeholders",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "code", name="uq_document_templates_company_code"),
        )
        op.create_index("ix_document_templates_company_id", "document_templates", ["company_id"])
        op.create_index(
            "ix_document_templates_company_active",
            "document_templates",
            ["company_id", "is_active"],
        )

    if not _has_table("document_generations"):
        op.create_table(
            "document_generations",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("output_object_key", sa.String(length=800), nullable=False),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("mime_type", sa.String(length=120), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column(
                "field_values",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=30), server_default="READY", nullable=False),
            sa.Column("rendered_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["template_id"], ["document_templates.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_document_generations_company_id", "document_generations", ["company_id"])
        op.create_index(
            "ix_document_generations_company_project",
            "document_generations",
            ["company_id", "project_id"],
        )
        op.create_index(
            "ix_document_generations_template",
            "document_generations",
            ["template_id"],
        )


def downgrade() -> None:
    if _has_table("document_generations"):
        op.drop_index("ix_document_generations_template", table_name="document_generations")
        op.drop_index("ix_document_generations_company_project", table_name="document_generations")
        op.drop_index("ix_document_generations_company_id", table_name="document_generations")
        op.drop_table("document_generations")

    if _has_table("document_templates"):
        op.drop_index("ix_document_templates_company_active", table_name="document_templates")
        op.drop_index("ix_document_templates_company_id", table_name="document_templates")
        op.drop_table("document_templates")
