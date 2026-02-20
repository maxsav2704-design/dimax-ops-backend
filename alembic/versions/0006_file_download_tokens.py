"""file download tokens

Revision ID: 0006_file_tokens
Revises: 0005_storage
Create Date: 2026-02-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0006_file_tokens"
down_revision = "0005_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_download_tokens",
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
        sa.Column("token", sa.String(length=120), nullable=False),
        sa.Column("object_key", sa.String(length=800), nullable=False),
        sa.Column("bucket", sa.String(length=100), nullable=False),
        sa.Column(
            "mime_type",
            sa.String(length=100),
            nullable=False,
            server_default="application/octet-stream",
        ),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "uses_left",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(length=64), nullable=True),
        sa.Column("last_used_ua", sa.Text(), nullable=True),
        sa.UniqueConstraint("token", name="uq_file_download_tokens_token"),
    )
    op.create_index(
        "ix_file_download_tokens_company_id",
        "file_download_tokens",
        ["company_id"],
    )
    op.create_index(
        "ix_file_download_tokens_expires_at",
        "file_download_tokens",
        ["expires_at"],
    )
    op.create_index(
        "ix_file_download_tokens_token",
        "file_download_tokens",
        ["token"],
    )


def downgrade() -> None:
    op.drop_table("file_download_tokens")
