"""Owner-scoped AI conversations, durable tasks and request replay keys."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0068_ai_memory"
down_revision = "0067_sync_price_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("ai_conversations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("admin_scope", sa.String(20), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "owner_user_id", "id", name="uq_ai_conversation_owner"),
        sa.ForeignKeyConstraint(["company_id", "owner_user_id"], ["admin_profiles.company_id", "admin_profiles.user_id"],
            ondelete="CASCADE", name="fk_ai_conversation_admin_owner"))
    op.create_index("ix_ai_conversations_company_id", "ai_conversations", ["company_id"])
    op.create_index("ix_ai_conversation_owner_updated", "ai_conversations", ["company_id", "owner_user_id", "updated_at"])
    op.create_table("ai_tasks",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(2), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reply", pg.JSONB()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "owner_user_id", "id", name="uq_ai_task_owner"),
        sa.UniqueConstraint("company_id", "owner_user_id", "request_id", name="uq_ai_task_request"),
        sa.ForeignKeyConstraint(["company_id", "owner_user_id", "conversation_id"],
            ["ai_conversations.company_id", "ai_conversations.owner_user_id", "ai_conversations.id"],
            ondelete="CASCADE", name="fk_ai_task_conversation_owner"),
        sa.CheckConstraint("status IN ('RUNNING','COMPLETED','FAILED','INTERRUPTED','CANCELLED')", name="ck_ai_task_status"),
        sa.CheckConstraint("attempt_count BETWEEN 1 AND 3", name="ck_ai_task_attempt_count"))
    op.create_index("ix_ai_tasks_company_id", "ai_tasks", ["company_id"])
    op.create_index("ix_ai_task_conversation_created", "ai_tasks", ["company_id", "conversation_id", "created_at"])
    op.create_index("uq_ai_task_running_conversation", "ai_tasks", ["conversation_id"], unique=True,
                    postgresql_where=sa.text("status = 'RUNNING'"))
    op.create_table("ai_task_attempts",
        sa.Column("company_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(8), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "owner_user_id", "task_id"],
            ["ai_tasks.company_id", "ai_tasks.owner_user_id", "ai_tasks.id"],
            ondelete="CASCADE", name="fk_ai_attempt_task_owner"))
    op.create_index("ix_ai_task_attempts_company_id", "ai_task_attempts", ["company_id"])


def downgrade() -> None:
    op.drop_table("ai_task_attempts")
    op.drop_table("ai_tasks")
    op.drop_table("ai_conversations")
