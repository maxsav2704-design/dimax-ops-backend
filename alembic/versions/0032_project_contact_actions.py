"""project contact actions

Revision ID: 0032_project_contact_actions
Revises: 0031_communication_templates
Create Date: 2026-03-28 18:05:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0032_project_contact_actions"
down_revision = "0031_communication_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("code", sa.String(length=40), nullable=True))
    op.add_column("projects", sa.Column("planned_start_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("planned_end_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("developer_phone_alt", sa.String(length=40), nullable=True))
    op.add_column("projects", sa.Column("developer_whatsapp", sa.String(length=40), nullable=True))
    op.add_column("projects", sa.Column("developer_notes", sa.String(length=1000), nullable=True))
    op.add_column("projects", sa.Column("address_street", sa.String(length=200), nullable=True))
    op.add_column("projects", sa.Column("address_building", sa.String(length=80), nullable=True))
    op.add_column("projects", sa.Column("address_city", sa.String(length=120), nullable=True))
    op.add_column("projects", sa.Column("address_entrance", sa.String(length=120), nullable=True))
    op.add_column("projects", sa.Column("address_lat", sa.Numeric(precision=10, scale=7), nullable=True))
    op.add_column("projects", sa.Column("address_lng", sa.Numeric(precision=10, scale=7), nullable=True))
    op.add_column("projects", sa.Column("address_waze_url", sa.String(length=500), nullable=True))

    op.execute(
        """
        UPDATE projects
        SET code = 'PRJ-' || UPPER(SUBSTRING(REPLACE(CAST(id AS text), '-', '') FROM 1 FOR 6))
        WHERE code IS NULL
        """
    )
    op.create_index(
        "ix_projects_company_code_active",
        "projects",
        ["company_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_projects_company_code_active", table_name="projects")
    op.drop_column("projects", "address_waze_url")
    op.drop_column("projects", "address_lng")
    op.drop_column("projects", "address_lat")
    op.drop_column("projects", "address_entrance")
    op.drop_column("projects", "address_city")
    op.drop_column("projects", "address_building")
    op.drop_column("projects", "address_street")
    op.drop_column("projects", "developer_notes")
    op.drop_column("projects", "developer_whatsapp")
    op.drop_column("projects", "developer_phone_alt")
    op.drop_column("projects", "planned_end_date")
    op.drop_column("projects", "planned_start_date")
    op.drop_column("projects", "code")
