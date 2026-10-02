"""Add expiring factory invitations and version-bound confirmation receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0064_factory_price_approval"
down_revision = "0063_factory_price_lists"
branch_labels = None
depends_on = None


def _status_check(confirmed: bool) -> str:
    allowed = "status IN ('DRAFT', 'CONFIRMED')" if confirmed else "status = 'DRAFT'"
    return (
        f"({allowed} AND cancelled_at IS NULL AND cancelled_by IS NULL AND cancellation_reason IS NULL) OR "
        "(status = 'CANCELLED' AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL "
        "AND cancellation_reason IS NOT NULL AND btrim(cancellation_reason) <> '')"
    )


def upgrade() -> None:
    op.drop_constraint("ck_factory_price_lists_status", "factory_price_lists", type_="check")
    op.create_check_constraint("ck_factory_price_lists_status", "factory_price_lists", _status_check(True))
    op.create_table(
        "factory_price_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_list_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("factory_name", sa.String(160), nullable=False),
        sa.Column("recipient_name", sa.String(160), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("revocation_reason", sa.String(1000)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_name", sa.String(160)),
        sa.ForeignKeyConstraint(
            ["company_id", "price_list_id"], ["factory_price_lists.company_id", "factory_price_lists.id"],
            ondelete="CASCADE", name="fk_factory_approvals_tenant_list",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_factory_approvals_expiry"),
        sa.CheckConstraint("btrim(factory_name) <> '' AND btrim(recipient_name) <> '' AND btrim(recipient_email) <> ''",
                           name="ck_factory_approvals_recipient"),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revocation_reason IS NOT NULL "
            "AND btrim(revocation_reason) <> '' AND confirmed_at IS NULL)", name="ck_factory_approvals_revocation",
        ),
        sa.CheckConstraint(
            "(confirmed_at IS NULL AND confirmed_name IS NULL) OR "
            "(confirmed_at IS NOT NULL AND confirmed_name IS NOT NULL AND btrim(confirmed_name) <> '' "
            "AND confirmed_at < expires_at AND revoked_at IS NULL)", name="ck_factory_approvals_confirmation",
        ),
    )
    op.create_index("ix_factory_price_approvals_price_list_id", "factory_price_approvals", ["price_list_id"])
    op.create_index("uq_factory_approvals_pending", "factory_price_approvals", ["price_list_id"], unique=True,
                    postgresql_where=sa.text("revoked_at IS NULL AND confirmed_at IS NULL"))
    op.create_index("uq_factory_approvals_confirmed", "factory_price_approvals", ["price_list_id"], unique=True,
                    postgresql_where=sa.text("confirmed_at IS NOT NULL"))


def downgrade() -> None:
    op.execute("LOCK TABLE factory_price_lists, factory_price_approvals IN ACCESS EXCLUSIVE MODE")
    history = op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM factory_price_approvals) OR "
                                           "EXISTS(SELECT 1 FROM factory_price_lists WHERE status = 'CONFIRMED')")).scalar_one()
    if history:
        raise RuntimeError("Cannot downgrade: factory invitation or confirmation history exists")
    op.drop_table("factory_price_approvals")
    op.drop_constraint("ck_factory_price_lists_status", "factory_price_lists", type_="check")
    op.create_check_constraint("ck_factory_price_lists_status", "factory_price_lists", _status_check(False))
