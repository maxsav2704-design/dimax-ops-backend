"""file download events audit

Revision ID: 0008_file_download_events
Revises: 0007_file_token_audience
Create Date: 2026-02-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0008_file_download_events"
down_revision = "0007_file_token_audience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_download_events",
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
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("token", sa.String(length=120), nullable=True),
        sa.Column("object_key", sa.String(length=800), nullable=False),
        sa.Column("bucket", sa.String(length=100), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "correlation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_file_download_events_company_id",
        "file_download_events",
        ["company_id"],
    )
    op.create_index(
        "ix_file_download_events_correlation_id",
        "file_download_events",
        ["correlation_id"],
    )
    op.create_index(
        "ix_file_download_events_created_at",
        "file_download_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("file_download_events")
