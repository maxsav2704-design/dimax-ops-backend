"""DIMAX AI background execution: a task is claimed by the API (inline mode) or by the AI worker.

`claimed_at` is NULL while a RUNNING task waits for a worker; the API sets it at start in inline
mode so a running worker never executes the same attempt twice.

Revision ID: 0081_ai_worker_claims
Revises: 0080_ai_installers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0081_ai_worker_claims"
down_revision = "0080_ai_installers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_tasks", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    # Existing RUNNING rows were started inline: never hand them to the worker.
    op.execute("UPDATE ai_tasks SET claimed_at = updated_at WHERE status = 'RUNNING'")
    op.create_index("ix_ai_task_worker_queue", "ai_tasks", ["created_at"], postgresql_where=sa.text("status = 'RUNNING' AND claimed_at IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_ai_task_worker_queue", table_name="ai_tasks")
    op.drop_column("ai_tasks", "claimed_at")
