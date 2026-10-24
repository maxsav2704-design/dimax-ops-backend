"""Explicit reconciliation gate for restored outbound messages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0089_outbox_recovery"
down_revision = "0088_work_stages"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_outbox_message_tenant", "outbox_messages", ["company_id", "id"])
    op.create_table(
        "outbox_recoveries",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("company_id", UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("epoch", UUID(), nullable=False),
        sa.Column("opened_by", UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("released_by", UUID(), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("company_id", "epoch", name="uq_outbox_recovery_epoch"),
        sa.UniqueConstraint("company_id", "id", name="uq_outbox_recovery_tenant"),
        sa.CheckConstraint("btrim(reason) <> ''", name="ck_outbox_recovery_reason"),
    )
    op.create_table(
        "outbox_recovery_items",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("company_id", UUID(), nullable=False),
        sa.Column("recovery_id", UUID(), nullable=False),
        sa.Column("outbox_id", UUID(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16)),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["company_id", "recovery_id"], ["outbox_recoveries.company_id", "outbox_recoveries.id"]),
        sa.ForeignKeyConstraint(["company_id", "outbox_id"], ["outbox_messages.company_id", "outbox_messages.id"]),
        sa.UniqueConstraint("recovery_id", "outbox_id", name="uq_outbox_recovery_item"),
        sa.UniqueConstraint("company_id", "id", name="uq_outbox_recovery_item_tenant"),
        sa.CheckConstraint("action IS NULL OR action IN ('HOLD', 'RETRY', 'ACCEPTED')", name="ck_outbox_recovery_action"),
        sa.CheckConstraint("revision >= 0", name="ck_outbox_recovery_revision"),
    )
    op.create_table(
        "outbox_recovery_decisions",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("company_id", UUID(), nullable=False),
        sa.Column("item_id", UUID(), nullable=False),
        sa.Column("request_id", UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("evidence", sa.String(1000), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("actor_id", UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "item_id"], ["outbox_recovery_items.company_id", "outbox_recovery_items.id"]),
        sa.UniqueConstraint("company_id", "request_id", name="uq_outbox_recovery_request"),
        sa.UniqueConstraint("item_id", "revision", name="uq_outbox_recovery_decision_revision"),
        sa.CheckConstraint("action IN ('HOLD', 'RETRY', 'ACCEPTED') AND revision > 0", name="ck_outbox_recovery_decision"),
        sa.CheckConstraint("btrim(reason) <> '' AND btrim(evidence) <> ''", name="ck_outbox_recovery_evidence"),
        sa.CheckConstraint("(action = 'ACCEPTED') = (accepted_at IS NOT NULL)", name="ck_outbox_recovery_accepted"),
    )
    op.execute("""
        CREATE FUNCTION outbox_recovery_decision_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'Recovery decisions are append-only';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER outbox_recovery_decision_immutable
        BEFORE UPDATE OR DELETE ON outbox_recovery_decisions
        FOR EACH ROW EXECUTE FUNCTION outbox_recovery_decision_immutable()
    """)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM outbox_recoveries)")).scalar():
        raise RuntimeError("Cannot discard recovery holds or decision history")
    op.drop_table("outbox_recovery_decisions")
    op.execute("DROP FUNCTION outbox_recovery_decision_immutable()")
    op.drop_table("outbox_recovery_items")
    op.drop_table("outbox_recoveries")
    op.drop_constraint("uq_outbox_message_tenant", "outbox_messages", type_="unique")
