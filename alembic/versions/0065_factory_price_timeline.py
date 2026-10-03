"""Record append-only effective price versions without changing legacy earnings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0065_factory_price_timeline"
down_revision = "0064_factory_price_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_factory_approvals_tenant_list_id", "factory_price_approvals", ["company_id", "price_list_id", "id"])
    op.create_table(
        "factory_price_activations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_list_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "price_list_id"], ["factory_price_lists.company_id", "factory_price_lists.id"],
                               ondelete="RESTRICT", name="fk_factory_activation_tenant_list"),
        sa.ForeignKeyConstraint(["company_id", "price_list_id", "approval_id"],
                               ["factory_price_approvals.company_id", "factory_price_approvals.price_list_id", "factory_price_approvals.id"],
                               ondelete="RESTRICT", name="fk_factory_activation_tenant_approval"),
        sa.UniqueConstraint("company_id", "price_list_id", name="uq_factory_activation_list"),
        sa.UniqueConstraint("company_id", "effective_from", name="uq_factory_activation_time"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_factory_activation_request"),
        sa.CheckConstraint("btrim(reason) <> ''", name="ck_factory_activation_reason"),
        sa.CheckConstraint("effective_from = created_at", name="ck_factory_activation_time"),
        sa.CheckConstraint("length(snapshot_hash) = 64 AND length(request_fingerprint) = 64", name="ck_factory_activation_hashes"),
    )


def downgrade() -> None:
    op.execute("LOCK TABLE factory_price_activations IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM factory_price_activations)")).scalar_one():
        raise RuntimeError("Cannot downgrade: effective factory price history exists")
    op.drop_table("factory_price_activations")
    op.drop_constraint("uq_factory_approvals_tenant_list_id", "factory_price_approvals", type_="unique")
