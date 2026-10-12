"""Immutable proposals for one retained work; no approvals or earnings are inferred."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0072_work_price_proposals"
down_revision = "0071_offline_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("work_price_proposals",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("sync_event_id", pg.UUID(as_uuid=True)),
        sa.Column("sync_queue_item_id", pg.UUID(as_uuid=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", pg.JSONB(), nullable=False),
        sa.Column("rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint("company_id", "id", name="uq_work_price_proposal_tenant"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_work_price_proposal_request"),
        sa.UniqueConstraint("company_id", "sync_event_id", "version", name="uq_work_price_proposal_event_version"),
        sa.UniqueConstraint("company_id", "sync_queue_item_id", "version", name="uq_work_price_proposal_queue_version"),
        sa.ForeignKeyConstraint(["company_id", "sync_event_id"], ["sync_events.company_id", "sync_events.id"],
                                ondelete="RESTRICT", name="fk_work_price_proposal_event"),
        sa.ForeignKeyConstraint(["company_id", "sync_queue_item_id"], ["sync_queue_items.company_id", "sync_queue_items.id"],
                                ondelete="RESTRICT", name="fk_work_price_proposal_queue"),
        sa.CheckConstraint("(sync_event_id IS NULL) <> (sync_queue_item_id IS NULL)", name="ck_work_price_proposal_source"),
        sa.CheckConstraint("version > 0 AND rate > 0 AND amount > 0", name="ck_work_price_proposal_values"),
        sa.CheckConstraint("length(request_fingerprint) = 64 AND length(snapshot_hash) = 64", name="ck_work_price_proposal_hashes"),
    )
    op.execute("""CREATE FUNCTION reject_work_price_proposal_change() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Work price proposals are immutable'; END;
        $$ LANGUAGE plpgsql""")
    op.execute("""CREATE TRIGGER work_price_proposal_immutable
        BEFORE UPDATE OR DELETE ON work_price_proposals FOR EACH ROW
        EXECUTE FUNCTION reject_work_price_proposal_change()""")


def downgrade():
    op.execute("LOCK TABLE work_price_proposals IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM work_price_proposals)")).scalar_one():
        raise RuntimeError("Cannot downgrade: retained work price proposals exist")
    op.drop_table("work_price_proposals")
    op.execute("DROP FUNCTION reject_work_price_proposal_change()")
