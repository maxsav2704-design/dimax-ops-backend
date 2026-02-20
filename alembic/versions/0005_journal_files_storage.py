"""journal_files storage columns

Revision ID: 0005_storage
Revises: 0004_outbox
Create Date: 2026-02-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_storage"
down_revision = "0004_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "journal_files",
        sa.Column(
            "storage_provider",
            sa.String(length=30),
            nullable=False,
            server_default="MINIO",
        ),
    )
    op.add_column(
        "journal_files",
        sa.Column(
            "bucket",
            sa.String(length=100),
            nullable=False,
            server_default="dimax",
        ),
    )


def downgrade() -> None:
    op.drop_column("journal_files", "bucket")
    op.drop_column("journal_files", "storage_provider")
