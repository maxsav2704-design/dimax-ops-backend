"""file token audience

Revision ID: 0007_file_token_audience
Revises: 0006_file_tokens
Create Date: 2026-02-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_file_token_audience"
down_revision = "0006_file_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file_download_tokens",
        sa.Column("audience", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("file_download_tokens", "audience")
