"""Persist factory mailbox challenges without asserting verification of past decisions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0069_factory_mailbox"
down_revision = "0068_ai_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("mailbox_challenge_id", pg.UUID(as_uuid=True)),
        sa.Column("mailbox_code_hash", sa.String(64)),
        sa.Column("mailbox_code_expires_at", sa.DateTime(timezone=True)),
        sa.Column("mailbox_requested_at", sa.DateTime(timezone=True)),
        sa.Column("mailbox_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mailbox_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mailbox_verified_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("factory_price_approvals", column)
    op.create_check_constraint("ck_factory_approvals_mailbox_limits", "factory_price_approvals",
                               "mailbox_requests BETWEEN 0 AND 10 AND mailbox_attempts BETWEEN 0 AND 5")
    op.create_check_constraint("ck_factory_approvals_mailbox_challenge", "factory_price_approvals",
        "(mailbox_code_hash IS NULL AND mailbox_challenge_id IS NULL AND mailbox_code_expires_at IS NULL "
        "AND mailbox_requested_at IS NULL) OR (mailbox_code_hash IS NOT NULL AND mailbox_challenge_id IS NOT NULL "
        "AND mailbox_code_expires_at IS NOT NULL AND mailbox_requested_at IS NOT NULL "
        "AND mailbox_code_expires_at > mailbox_requested_at AND mailbox_requests > 0)")
    op.create_check_constraint("ck_factory_approvals_mailbox_verified", "factory_price_approvals",
        "mailbox_verified_at IS NULL OR (confirmed_at IS NOT NULL "
        "AND mailbox_code_hash IS NOT NULL AND mailbox_verified_at = confirmed_at)")


def downgrade() -> None:
    # A rollback must not erase evidence or reopen a used brute-force budget.
    op.execute("LOCK TABLE factory_price_approvals IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM factory_price_approvals WHERE mailbox_requests > 0 "
        "OR mailbox_verified_at IS NOT NULL)"
    )).scalar():
        raise RuntimeError("Cannot discard factory mailbox verification history")
    for name in ("verified", "challenge", "limits"):
        op.drop_constraint(f"ck_factory_approvals_mailbox_{name}", "factory_price_approvals", type_="check")
    for name in ("verified_at", "attempts", "requests", "requested_at", "code_expires_at", "code_hash", "challenge_id"):
        op.drop_column("factory_price_approvals", f"mailbox_{name}")
