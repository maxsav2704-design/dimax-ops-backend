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


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "installer_profiles"):
        return

    op.create_table(
        "installer_profiles",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "installer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("installers.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_installer_profiles_language'
          ) THEN
            ALTER TABLE installer_profiles
              ADD CONSTRAINT ck_installer_profiles_language
              CHECK (language IN ('ru', 'en', 'he'));
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "installer_profiles"):
        return

    op.drop_table("installer_profiles")
