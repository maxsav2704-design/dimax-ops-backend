"""Store immutable company-wide price-list drafts without activating legacy prices."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0063_factory_price_lists"
down_revision = "0062_issue_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "factory_price_lists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("agreement_reference", sa.String(500), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("cancellation_reason", sa.String(1000)),
        sa.UniqueConstraint("company_id", "id", name="uq_factory_price_lists_tenant_id"),
        sa.UniqueConstraint("company_id", "version", name="uq_factory_price_lists_version"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_factory_price_lists_request"),
        sa.CheckConstraint("version > 0", name="ck_factory_price_lists_version"),
        sa.CheckConstraint("currency = 'ILS'", name="ck_factory_price_lists_currency"),
        sa.CheckConstraint("btrim(reason) <> '' AND btrim(agreement_reference) <> ''", name="ck_factory_price_lists_reference"),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND cancelled_at IS NULL AND cancelled_by IS NULL "
            "AND cancellation_reason IS NULL) OR "
            "(status = 'CANCELLED' AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL "
            "AND cancellation_reason IS NOT NULL AND btrim(cancellation_reason) <> '')",
            name="ck_factory_price_lists_status",
        ),
    )
    op.create_table(
        "factory_price_list_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_list_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("door_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("door_types.id", ondelete="RESTRICT")),
        sa.Column("addon_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("addon_types.id", ondelete="RESTRICT")),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("installer_price", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "price_list_id"], ["factory_price_lists.company_id", "factory_price_lists.id"],
            ondelete="CASCADE", name="fk_factory_price_items_tenant_list",
        ),
        sa.UniqueConstraint("price_list_id", "door_type_id", name="uq_factory_price_items_door"),
        sa.UniqueConstraint("price_list_id", "addon_type_id", name="uq_factory_price_items_addon"),
        sa.CheckConstraint(
            "(kind = 'DOOR' AND door_type_id IS NOT NULL AND addon_type_id IS NULL) OR "
            "(kind = 'ADDON' AND addon_type_id IS NOT NULL AND door_type_id IS NULL)",
            name="ck_factory_price_items_target",
        ),
        sa.CheckConstraint("installer_price > 0 AND installer_price < 10000000000", name="ck_factory_price_items_price"),
        sa.CheckConstraint("btrim(name) <> '' AND btrim(unit) <> ''", name="ck_factory_price_items_label"),
    )
    op.create_index("ix_factory_price_list_items_price_list_id", "factory_price_list_items", ["price_list_id"])


def downgrade() -> None:
    # Refuse destructive rollback after a draft has been recorded.
    op.execute("LOCK TABLE factory_price_lists IN ACCESS EXCLUSIVE MODE")
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM factory_price_lists")).scalar_one()
    if count:
        raise RuntimeError("Cannot downgrade: factory price list history exists; export and review it first")
    op.drop_table("factory_price_list_items")
    op.drop_table("factory_price_lists")
