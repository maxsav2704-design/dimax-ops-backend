"""Add communication templates.

Revision ID: 0031_communication_templates
Revises: 0030_door_order_number
Create Date: 2026-03-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_communication_templates"
down_revision = "0030_door_order_number"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communication_templates",
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("send_email", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "send_whatsapp", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "company_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "code",
            name="uq_communication_templates_company_code",
        ),
    )
    op.create_index(
        op.f("ix_communication_templates_company_id"),
        "communication_templates",
        ["company_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_communication_templates_company_id"),
        table_name="communication_templates",
    )
    op.drop_table("communication_templates")
