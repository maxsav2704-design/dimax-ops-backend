"""Stage earnings (step 4): factory-confirmed rates per door type and work stage, and ledger rows
valued from stage execution facts.

- factory_price_list_items: kind STAGE keyed by (door_type_id, stage_code); the stage code must exist
  in the company's stage catalog. DOOR and ADDON lines are untouched (same constraints, same names).
- completed_work: work_kind STAGE with door_id AND stage_fact_id (one ORIGINAL per stage fact);
  the immutability guard now also covers stage_fact_id.
- sync_change_type: DOOR_STAGES (stage plan/assignments/facts pushed to the installers of a door).

Revision ID: 0090_stage_earnings
Revises: 0089_outbox_recovery
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0090_stage_earnings"
down_revision = "0089_outbox_recovery"
branch_labels = None
depends_on = None

ITEM_TARGET_V2 = (
    "(kind = 'DOOR' AND door_type_id IS NOT NULL AND addon_type_id IS NULL AND stage_code IS NULL) OR "
    "(kind = 'ADDON' AND addon_type_id IS NOT NULL AND door_type_id IS NULL AND stage_code IS NULL) OR "
    "(kind = 'STAGE' AND door_type_id IS NOT NULL AND stage_code IS NOT NULL AND addon_type_id IS NULL)"
)
ITEM_TARGET_V1 = (
    "(kind = 'DOOR' AND door_type_id IS NOT NULL AND addon_type_id IS NULL) OR "
    "(kind = 'ADDON' AND addon_type_id IS NOT NULL AND door_type_id IS NULL)"
)
WORK_SUBJECT_V2 = (
    "(work_kind = 'DOOR' AND door_id IS NOT NULL AND addon_fact_id IS NULL AND stage_fact_id IS NULL) OR "
    "(work_kind = 'ADDON' AND door_id IS NULL AND addon_fact_id IS NOT NULL AND stage_fact_id IS NULL) OR "
    "(work_kind = 'STAGE' AND door_id IS NOT NULL AND stage_fact_id IS NOT NULL AND addon_fact_id IS NULL)"
)
WORK_SUBJECT_V1 = (
    "(work_kind = 'DOOR' AND door_id IS NOT NULL AND addon_fact_id IS NULL) OR "
    "(work_kind = 'ADDON' AND door_id IS NULL AND addon_fact_id IS NOT NULL)"
)

LEDGER_GUARD_COLUMNS_V1 = [
    "company_id", "installer_id", "completed_at", "quantity", "rate_snapshot", "amount_snapshot",
    "work_kind", "entry_type", "correction_ref_id", "reason",
]
LEDGER_GUARD_COLUMNS_V2 = LEDGER_GUARD_COLUMNS_V1 + ["stage_fact_id"]


def _ledger_guard(columns):
    checks = "\n           OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in columns)
    return f"""
        CREATE OR REPLACE FUNCTION protect_completed_work_ledger() RETURNS trigger AS $$
        BEGIN
        IF TG_OP = 'DELETE' THEN
          RAISE EXCEPTION 'Recorded earnings are immutable: corrections are new rows';
        END IF;
        IF {checks} THEN
          RAISE EXCEPTION 'Recorded earnings are immutable: corrections are new rows';
        END IF;
        RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """


def upgrade():
    # --- price list: STAGE lines ---------------------------------------------------------------
    op.add_column("factory_price_list_items", sa.Column("stage_code", sa.String(40)))
    op.create_foreign_key("fk_factory_price_items_stage", "factory_price_list_items", "work_stage_definitions",
                          ["company_id", "stage_code"], ["company_id", "code"], ondelete="RESTRICT")
    op.drop_constraint("ck_factory_price_items_target", "factory_price_list_items", type_="check")
    op.create_check_constraint("ck_factory_price_items_target", "factory_price_list_items", ITEM_TARGET_V2)
    # One DOOR line per door type stays unique; STAGE lines share the door type, so the rule becomes partial.
    op.drop_constraint("uq_factory_price_items_door", "factory_price_list_items", type_="unique")
    op.create_index("uq_factory_price_items_door", "factory_price_list_items", ["price_list_id", "door_type_id"],
                    unique=True, postgresql_where=sa.text("kind = 'DOOR'"))
    op.create_index("uq_factory_price_items_stage", "factory_price_list_items",
                    ["price_list_id", "door_type_id", "stage_code"], unique=True,
                    postgresql_where=sa.text("kind = 'STAGE'"))

    # --- ledger: STAGE rows --------------------------------------------------------------------
    op.add_column("completed_work", sa.Column("stage_fact_id", pg.UUID(as_uuid=True)))
    op.create_foreign_key("fk_completed_work_stage_fact", "completed_work", "door_stage_facts",
                          ["stage_fact_id"], ["id"], ondelete="RESTRICT")
    op.drop_constraint("ck_completed_work_work_kind", "completed_work", type_="check")
    op.create_check_constraint("ck_completed_work_work_kind", "completed_work", "work_kind IN ('DOOR', 'ADDON', 'STAGE')")
    op.drop_constraint("ck_completed_work_subject", "completed_work", type_="check")
    op.create_check_constraint("ck_completed_work_subject", "completed_work", WORK_SUBJECT_V2)
    op.create_index("uq_completed_work_stage_fact_original", "completed_work", ["stage_fact_id"], unique=True,
                    postgresql_where=sa.text("stage_fact_id IS NOT NULL AND entry_type = 'ORIGINAL'"))
    op.execute(_ledger_guard(LEDGER_GUARD_COLUMNS_V2))

    # --- sync: stage data for the installers of a door ----------------------------------------
    op.execute("ALTER TYPE sync_change_type ADD VALUE IF NOT EXISTS 'DOOR_STAGES'")


def downgrade():
    bind = op.get_bind()
    op.execute("LOCK TABLE completed_work IN ACCESS EXCLUSIVE MODE")
    if bind.execute(sa.text("SELECT EXISTS(SELECT 1 FROM completed_work WHERE work_kind = 'STAGE')")).scalar_one():
        raise RuntimeError("Cannot discard recorded stage earnings")
    if bind.execute(sa.text("SELECT EXISTS(SELECT 1 FROM factory_price_list_items WHERE kind = 'STAGE')")).scalar_one():
        raise RuntimeError("Cannot discard factory-confirmed stage prices")
    op.execute(_ledger_guard(LEDGER_GUARD_COLUMNS_V1))
    op.drop_index("uq_completed_work_stage_fact_original", table_name="completed_work")
    op.drop_constraint("ck_completed_work_subject", "completed_work", type_="check")
    op.create_check_constraint("ck_completed_work_subject", "completed_work", WORK_SUBJECT_V1)
    op.drop_constraint("ck_completed_work_work_kind", "completed_work", type_="check")
    op.create_check_constraint("ck_completed_work_work_kind", "completed_work", "work_kind IN ('DOOR', 'ADDON')")
    op.drop_constraint("fk_completed_work_stage_fact", "completed_work", type_="foreignkey")
    op.drop_column("completed_work", "stage_fact_id")

    op.drop_index("uq_factory_price_items_stage", table_name="factory_price_list_items")
    op.drop_index("uq_factory_price_items_door", table_name="factory_price_list_items")
    op.create_unique_constraint("uq_factory_price_items_door", "factory_price_list_items", ["price_list_id", "door_type_id"])
    op.drop_constraint("ck_factory_price_items_target", "factory_price_list_items", type_="check")
    op.create_check_constraint("ck_factory_price_items_target", "factory_price_list_items", ITEM_TARGET_V1)
    op.drop_constraint("fk_factory_price_items_stage", "factory_price_list_items", type_="foreignkey")
    op.drop_column("factory_price_list_items", "stage_code")
    # The enum value DOOR_STAGES stays: PostgreSQL cannot drop enum values in place.
