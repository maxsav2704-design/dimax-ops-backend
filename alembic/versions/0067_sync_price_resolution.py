"""Audited price conflict decisions; original commands and earnings remain intact."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0067_sync_price_resolution"
down_revision = "0066_factory_earning_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_sync_events_tenant_id", "sync_events", ["company_id", "id"])
    op.create_unique_constraint("uq_sync_queue_tenant_id", "sync_queue_items", ["company_id", "id"])
    op.create_table("sync_price_resolutions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("sync_event_id", pg.UUID(as_uuid=True)),
        sa.Column("sync_queue_item_id", pg.UUID(as_uuid=True)),
        sa.Column("completed_work_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("review_token", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("original_command", pg.JSONB(), nullable=False),
        sa.Column("quote_snapshot", pg.JSONB(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "request_id", name="uq_sync_price_resolution_request"),
        sa.UniqueConstraint("company_id", "sync_event_id", name="uq_sync_price_resolution_event"),
        sa.UniqueConstraint("company_id", "sync_queue_item_id", name="uq_sync_price_resolution_queue"),
        sa.UniqueConstraint("completed_work_id", name="uq_sync_price_resolution_work"),
        sa.ForeignKeyConstraint(["company_id", "sync_event_id"], ["sync_events.company_id", "sync_events.id"],
                                ondelete="RESTRICT", name="fk_sync_price_resolution_event"),
        sa.ForeignKeyConstraint(["company_id", "sync_queue_item_id"], ["sync_queue_items.company_id", "sync_queue_items.id"],
                                ondelete="RESTRICT", name="fk_sync_price_resolution_queue"),
        sa.ForeignKeyConstraint(["company_id", "completed_work_id"], ["completed_work.company_id", "completed_work.id"],
                                ondelete="RESTRICT", name="fk_sync_price_resolution_work"),
        sa.CheckConstraint("(sync_event_id IS NULL) <> (sync_queue_item_id IS NULL)", name="ck_sync_price_resolution_source"),
        sa.CheckConstraint("amount > 0 AND length(btrim(reason)) BETWEEN 10 AND 500", name="ck_sync_price_resolution_decision"),
    )
    op.execute("""CREATE FUNCTION reject_sync_price_resolution_change() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Price resolution decisions are immutable'; END;
        $$ LANGUAGE plpgsql""")
    op.execute("""CREATE TRIGGER sync_price_resolution_immutable
        BEFORE UPDATE OR DELETE ON sync_price_resolutions FOR EACH ROW
        EXECUTE FUNCTION reject_sync_price_resolution_change()""")


def downgrade() -> None:
    op.execute("LOCK TABLE sync_price_resolutions IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM sync_price_resolutions)")).scalar_one():
        raise RuntimeError("Cannot downgrade: audited price resolutions exist")
    op.drop_table("sync_price_resolutions")
    op.execute("DROP FUNCTION reject_sync_price_resolution_change()")
    op.drop_constraint("uq_sync_queue_tenant_id", "sync_queue_items", type_="unique")
    op.drop_constraint("uq_sync_events_tenant_id", "sync_events", type_="unique")
