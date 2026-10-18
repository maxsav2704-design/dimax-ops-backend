"""DIMAX AI proposals: a business action the agent prepared and an admin must confirm.

The agent never executes a command from the model loop. An action tool only
stores a proposal (arguments, preview, expected versions). Confirmation is a
separate authenticated request that re-checks rights, versions and executes the
existing business command once (confirm_request_id makes it idempotent).

Revision ID: 0079_ai_proposals
Revises: 0078_project_risks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0079_ai_proposals"
down_revision = "0078_project_risks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_tasks", sa.Column("context", pg.JSONB(), nullable=True))
    op.create_table(
        "ai_proposals",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(40), nullable=False),
        sa.Column("arguments", pg.JSONB(), nullable=False),
        sa.Column("preview", pg.JSONB(), nullable=False),
        sa.Column("expected", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("confirm_request_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("result", pg.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "owner_user_id", "task_id"],
            ["ai_tasks.company_id", "ai_tasks.owner_user_id", "ai_tasks.id"],
            ondelete="CASCADE", name="fk_ai_proposal_task_owner",
        ),
        sa.CheckConstraint(
            "status IN ('PROPOSED','CONFIRMED','EXECUTED','REJECTED','EXPIRED','FAILED','CONFLICT')",
            name="ck_ai_proposal_status",
        ),
    )
    op.create_index("ix_ai_proposals_company_id", "ai_proposals", ["company_id"])
    op.create_index("ix_ai_proposal_task", "ai_proposals", ["company_id", "task_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_proposal_task", table_name="ai_proposals")
    op.drop_index("ix_ai_proposals_company_id", table_name="ai_proposals")
    op.drop_table("ai_proposals")
    op.drop_column("ai_tasks", "context")
