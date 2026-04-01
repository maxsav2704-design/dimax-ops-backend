"""installer profiles table

Revision ID: 0034_installer_profiles_table
Revises: 0033_users_status_column
Create Date: 2026-03-31 00:01:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0034_installer_profiles_table"
down_revision = "0033_users_status_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "installer_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("company_id", "user_id", name="uq_installer_profiles_company_user"),
    )
    op.create_index("ix_installer_profiles_company_id", "installer_profiles", ["company_id"])
    op.create_index("ix_installer_profiles_user_id", "installer_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_installer_profiles_user_id", table_name="installer_profiles")
    op.drop_index("ix_installer_profiles_company_id", table_name="installer_profiles")
    op.drop_table("installer_profiles")
