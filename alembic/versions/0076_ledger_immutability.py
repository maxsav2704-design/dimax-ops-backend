"""Database-level immutability for recorded earnings and confirmed factory prices.

Product rule: recorded earnings are never edited or deleted, corrections are
new rows; a confirmed factory price list and its activation are history. The
application never updated these rows, but nothing in the database refused it.

Guards (all idempotent, safe to re-run on a database built from the ORM):
- completed_work: no DELETE; no UPDATE of the money / identity columns
  (foreign keys may still be set NULL by a parent delete, the ledger row stays).
- factory_earning_prices: no UPDATE, no DELETE.
- factory_price_list_items: no UPDATE / DELETE once the list left DRAFT.
- factory_price_lists: no DELETE once the list left DRAFT (status changes are
  application logic; version and company are covered by constraints).
- factory_price_activations: no UPDATE, no DELETE.

Revision ID: 0076_ledger_immutability
Revises: 0075_sync_hot_path_indexes
"""

from __future__ import annotations

from alembic import op

revision = "0076_ledger_immutability"
down_revision = "0075_sync_hot_path_indexes"
branch_labels = None
depends_on = None

GUARDS = {
    "completed_work": (
        "protect_completed_work_ledger",
        """
        IF TG_OP = 'DELETE' THEN
          RAISE EXCEPTION 'Recorded earnings are immutable: corrections are new rows';
        END IF;
        IF NEW.company_id IS DISTINCT FROM OLD.company_id
           OR NEW.installer_id IS DISTINCT FROM OLD.installer_id
           OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
           OR NEW.quantity IS DISTINCT FROM OLD.quantity
           OR NEW.rate_snapshot IS DISTINCT FROM OLD.rate_snapshot
           OR NEW.amount_snapshot IS DISTINCT FROM OLD.amount_snapshot
           OR NEW.work_kind IS DISTINCT FROM OLD.work_kind
           OR NEW.entry_type IS DISTINCT FROM OLD.entry_type
           OR NEW.correction_ref_id IS DISTINCT FROM OLD.correction_ref_id
           OR NEW.reason IS DISTINCT FROM OLD.reason THEN
          RAISE EXCEPTION 'Recorded earnings are immutable: corrections are new rows';
        END IF;
        RETURN NEW;
        """,
    ),
    "factory_earning_prices": (
        "protect_factory_earning_price",
        """
        RAISE EXCEPTION 'Factory earning price evidence is immutable';
        """,
    ),
    "factory_price_list_items": (
        "protect_confirmed_price_list_item",
        """
        IF EXISTS (SELECT 1 FROM factory_price_lists
                   WHERE id = OLD.price_list_id AND status <> 'DRAFT') THEN
          RAISE EXCEPTION 'Items of a confirmed price list are immutable: create a new version';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
        """,
    ),
    "factory_price_lists": (
        "protect_confirmed_price_list",
        """
        IF TG_OP = 'DELETE' THEN
          IF OLD.status <> 'DRAFT' THEN
            RAISE EXCEPTION 'A confirmed price list is history and cannot be deleted';
          END IF;
          RETURN OLD;
        END IF;
        RETURN NEW;
        """,
    ),
    "factory_price_activations": (
        "protect_price_activation",
        """
        RAISE EXCEPTION 'Factory price activations are immutable';
        """,
    ),
}


def upgrade() -> None:
    for table, (function_name, body) in GUARDS.items():
        op.execute(
            f"CREATE OR REPLACE FUNCTION {function_name}() RETURNS trigger AS $$\n"
            f"BEGIN\n{body}\nEND; $$ LANGUAGE plpgsql"
        )
        op.execute(f"DROP TRIGGER IF EXISTS {function_name}_guard ON {table}")
        op.execute(
            f"CREATE TRIGGER {function_name}_guard BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function_name}()"
        )


def downgrade() -> None:
    for table, (function_name, _body) in GUARDS.items():
        op.execute(f"DROP TRIGGER IF EXISTS {function_name}_guard ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {function_name}()")
