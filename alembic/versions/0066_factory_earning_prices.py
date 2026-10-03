"""Retain the factory price evidence of new earnings; never reprice existing work."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0066_factory_earning_prices"
down_revision = "0065_factory_price_timeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_completed_work_tenant_id", "completed_work", ["company_id", "id"])
    op.create_unique_constraint("uq_factory_price_items_tenant_list_id", "factory_price_list_items", ["company_id", "price_list_id", "id"])
    op.create_unique_constraint("uq_factory_activation_tenant_id", "factory_price_activations", ["company_id", "id"])
    op.create_table(
        "factory_earning_prices",
        sa.Column("completed_work_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_list_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_list_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("selection", sa.String(32), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("confirmed_rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "completed_work_id"], ["completed_work.company_id", "completed_work.id"],
                                ondelete="RESTRICT", name="fk_factory_earning_work"),
        sa.ForeignKeyConstraint(["company_id", "price_list_id", "price_list_item_id"],
            ["factory_price_list_items.company_id", "factory_price_list_items.price_list_id", "factory_price_list_items.id"],
            ondelete="RESTRICT", name="fk_factory_earning_item"),
        sa.ForeignKeyConstraint(["company_id", "price_list_id", "approval_id"],
            ["factory_price_approvals.company_id", "factory_price_approvals.price_list_id", "factory_price_approvals.id"],
            ondelete="RESTRICT", name="fk_factory_earning_approval"),
        sa.ForeignKeyConstraint(["company_id", "activation_id"], ["factory_price_activations.company_id", "factory_price_activations.id"],
                                ondelete="RESTRICT", name="fk_factory_earning_activation"),
        sa.CheckConstraint("selection IN ('AT_EXECUTION', 'FIRST_CONFIRMED_LEGACY')", name="ck_factory_earning_selection"),
        sa.CheckConstraint("confirmed_rate > 0 AND confirmed_rate < 10000000000", name="ck_factory_earning_rate"),
        sa.CheckConstraint("version > 0 AND currency = 'ILS' AND btrim(unit) <> '' AND length(snapshot_hash) = 64",
                           name="ck_factory_earning_snapshot"),
    )
    op.add_column("sync_queue_items", sa.Column("client_happened_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.execute("LOCK TABLE factory_earning_prices, sync_queue_items IN ACCESS EXCLUSIVE MODE")
    used = op.get_bind().execute(sa.text(
        "SELECT EXISTS(SELECT 1 FROM factory_earning_prices) OR "
        "EXISTS(SELECT 1 FROM sync_queue_items WHERE client_happened_at IS NOT NULL)"
    )).scalar_one()
    if used:
        raise RuntimeError("Cannot downgrade: factory earning evidence or offline execution times exist")
    op.drop_column("sync_queue_items", "client_happened_at")
    op.drop_table("factory_earning_prices")
    op.drop_constraint("uq_factory_activation_tenant_id", "factory_price_activations", type_="unique")
    op.drop_constraint("uq_factory_price_items_tenant_list_id", "factory_price_list_items", type_="unique")
    op.drop_constraint("uq_completed_work_tenant_id", "completed_work", type_="unique")
