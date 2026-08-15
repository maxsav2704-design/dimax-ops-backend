"""Enforce payroll, pricing, and add-on data integrity.

Revision ID: 0056_financial_data_integrity
Revises: 0055_project_operational_status
Create Date: 2026-07-16

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0056_financial_data_integrity"
down_revision = "0055_project_operational_status"
branch_labels = None
depends_on = None


def _check_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
    }


def _assert_no_invalid_rows(
    table_name: str,
    predicate: str,
    *,
    invariant: str,
) -> None:
    row = op.get_bind().execute(
        sa.text(f"SELECT id FROM {table_name} WHERE {predicate} LIMIT 1")
    ).first()
    if row is not None:
        raise RuntimeError(
            f"Cannot enforce {invariant}: {table_name} contains invalid row {row[0]}"
        )


def _add_check(table_name: str, name: str, condition: str) -> None:
    if name not in _check_names(table_name):
        op.create_check_constraint(name, table_name, condition)


def _drop_check(table_name: str, name: str) -> None:
    if name in _check_names(table_name):
        op.drop_constraint(name, table_name, type_="check")


def upgrade() -> None:
    _assert_no_invalid_rows(
        "completed_work",
        """
        quantity <= 0
        OR work_kind NOT IN ('DOOR', 'ADDON')
        OR NOT (
            (entry_type = 'ORIGINAL' AND correction_ref_id IS NULL)
            OR (
                entry_type IN ('REVERSAL', 'CORRECTION')
                AND correction_ref_id IS NOT NULL
            )
        )
        OR NOT (
            (
                entry_type = 'REVERSAL'
                AND rate_snapshot < 0
                AND amount_snapshot < 0
            )
            OR (
                entry_type IN ('ORIGINAL', 'CORRECTION')
                AND rate_snapshot > 0
                AND amount_snapshot > 0
            )
        )
        OR NOT (
            (
                work_kind = 'DOOR'
                AND door_id IS NOT NULL
                AND addon_fact_id IS NULL
            )
            OR (
                work_kind = 'ADDON'
                AND door_id IS NULL
                AND addon_fact_id IS NOT NULL
            )
        )
        """,
        invariant="completed work ledger integrity",
    )
    _assert_no_invalid_rows(
        "client_price_snapshots",
        "base_client_rate < 0 OR final_client_rate < 0 OR final_installer_rate <= 0",
        invariant="client price snapshot rates",
    )
    _assert_no_invalid_rows(
        "addon_types",
        "default_client_price < 0 OR default_installer_price < 0",
        invariant="add-on type prices",
    )
    _assert_no_invalid_rows(
        "project_addon_plans",
        "qty_planned < 0 OR client_price < 0 OR installer_price < 0",
        invariant="add-on plan values",
    )
    _assert_no_invalid_rows(
        "project_addon_facts",
        "qty_done <= 0",
        invariant="completed add-on quantity",
    )
    _assert_no_invalid_rows(
        "doors",
        """
        (installer_rate_snapshot IS NOT NULL AND installer_rate_snapshot <= 0)
        OR surcharge_pct < 0
        OR version < 0
        """,
        invariant="door financial snapshot and version values",
    )

    _add_check(
        "completed_work",
        "ck_completed_work_work_kind",
        "work_kind IN ('DOOR', 'ADDON')",
    )
    _add_check(
        "completed_work",
        "ck_completed_work_quantity_positive",
        "quantity > 0",
    )
    _add_check(
        "completed_work",
        "ck_completed_work_correction_ref",
        """
        (entry_type = 'ORIGINAL' AND correction_ref_id IS NULL)
        OR (
            entry_type IN ('REVERSAL', 'CORRECTION')
            AND correction_ref_id IS NOT NULL
        )
        """,
    )
    _add_check(
        "completed_work",
        "ck_completed_work_amount_sign",
        """
        (
            entry_type = 'REVERSAL'
            AND rate_snapshot < 0
            AND amount_snapshot < 0
        )
        OR (
            entry_type IN ('ORIGINAL', 'CORRECTION')
            AND rate_snapshot > 0
            AND amount_snapshot > 0
        )
        """,
    )
    _add_check(
        "completed_work",
        "ck_completed_work_subject",
        """
        (work_kind = 'DOOR' AND door_id IS NOT NULL AND addon_fact_id IS NULL)
        OR (
            work_kind = 'ADDON'
            AND door_id IS NULL
            AND addon_fact_id IS NOT NULL
        )
        """,
    )
    _add_check(
        "client_price_snapshots",
        "ck_client_price_snapshots_rates",
        "base_client_rate >= 0 AND final_client_rate >= 0 AND final_installer_rate > 0",
    )
    _add_check(
        "addon_types",
        "ck_addon_types_prices",
        "default_client_price >= 0 AND default_installer_price >= 0",
    )
    _add_check(
        "project_addon_plans",
        "ck_project_addon_plans_values",
        "qty_planned >= 0 AND client_price >= 0 AND installer_price >= 0",
    )
    _add_check(
        "project_addon_facts",
        "ck_project_addon_facts_qty",
        "qty_done > 0",
    )
    _add_check(
        "doors",
        "ck_doors_installer_rate_positive",
        "installer_rate_snapshot IS NULL OR installer_rate_snapshot > 0",
    )
    _add_check(
        "doors",
        "ck_doors_surcharge_nonnegative",
        "surcharge_pct >= 0",
    )
    _add_check(
        "doors",
        "ck_doors_version_nonnegative",
        "version >= 0",
    )


def downgrade() -> None:
    constraints = (
        ("doors", "ck_doors_version_nonnegative"),
        ("doors", "ck_doors_surcharge_nonnegative"),
        ("doors", "ck_doors_installer_rate_positive"),
        ("project_addon_facts", "ck_project_addon_facts_qty"),
        ("project_addon_plans", "ck_project_addon_plans_values"),
        ("addon_types", "ck_addon_types_prices"),
        ("client_price_snapshots", "ck_client_price_snapshots_rates"),
        ("completed_work", "ck_completed_work_subject"),
        ("completed_work", "ck_completed_work_amount_sign"),
        ("completed_work", "ck_completed_work_correction_ref"),
        ("completed_work", "ck_completed_work_quantity_positive"),
        ("completed_work", "ck_completed_work_work_kind"),
    )
    for table_name, name in constraints:
        _drop_check(table_name, name)