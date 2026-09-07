"""Create product library items table.

Revision ID: 0049_product_library_items
Revises: 0048_users_email_citext
Create Date: 2026-04-30 00:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "0049_product_library_items"
down_revision = "0048_users_email_citext"
branch_labels = None
depends_on = None


LEGACY_TABLE = "product_library"
CANONICAL_TABLE = "product_library_items"
UNIQUE_CONSTRAINT = "uq_product_library_company_sku"
LEGACY_UNIQUE_CONSTRAINT = "uq_product_library_legacy_company_sku"
LEGACY_INDEX_RENAMES = {
    "ix_product_library_items_company_id": "ix_product_library_legacy_company_id",
    "ix_product_library_company_status": "ix_product_library_legacy_company_status",
    "ix_product_library_install_type": "ix_product_library_legacy_install_type",
}


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _constraint_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    names = {
        str(item["name"])
        for item in inspector.get_unique_constraints(table_name)
        if item.get("name")
    }
    return names


def _index_names(table_name: str) -> set[str]:
    return {
        str(item["name"])
        for item in sa.inspect(op.get_bind()).get_indexes(table_name)
        if item.get("name")
    }


def _rename_legacy_relations() -> None:
    constraint_names = _constraint_names(LEGACY_TABLE)
    if UNIQUE_CONSTRAINT in constraint_names:
        op.execute(
            f'ALTER TABLE "{LEGACY_TABLE}" RENAME CONSTRAINT '
            f'"{UNIQUE_CONSTRAINT}" TO "{LEGACY_UNIQUE_CONSTRAINT}"'
        )
    elif LEGACY_UNIQUE_CONSTRAINT not in constraint_names:
        index_names = _index_names(LEGACY_TABLE)
        if UNIQUE_CONSTRAINT not in index_names:
            raise RuntimeError(
                "Legacy product_library must have a unique company_id/sku relation"
            )
        op.execute(
            f'ALTER INDEX "{UNIQUE_CONSTRAINT}" RENAME TO '
            f'"{LEGACY_UNIQUE_CONSTRAINT}"'
        )

    index_names = _index_names(LEGACY_TABLE)
    for current_name, legacy_name in LEGACY_INDEX_RENAMES.items():
        if current_name in index_names:
            op.execute(
                f'ALTER INDEX "{current_name}" RENAME TO "{legacy_name}"'
            )


def _restore_legacy_relation_names() -> None:
    constraint_names = _constraint_names(LEGACY_TABLE)
    if LEGACY_UNIQUE_CONSTRAINT in constraint_names:
        op.execute(
            f'ALTER TABLE "{LEGACY_TABLE}" RENAME CONSTRAINT '
            f'"{LEGACY_UNIQUE_CONSTRAINT}" TO "{UNIQUE_CONSTRAINT}"'
        )
    else:
        index_names = _index_names(LEGACY_TABLE)
        if LEGACY_UNIQUE_CONSTRAINT in index_names:
            op.execute(
                f'ALTER INDEX "{LEGACY_UNIQUE_CONSTRAINT}" RENAME TO '
                f'"{UNIQUE_CONSTRAINT}"'
            )

    index_names = _index_names(LEGACY_TABLE)
    for current_name, legacy_name in LEGACY_INDEX_RENAMES.items():
        if legacy_name in index_names:
            op.execute(
                f'ALTER INDEX "{legacy_name}" RENAME TO "{current_name}"'
            )


def _validate_legacy_upgrade_rows() -> None:
    invalid = op.get_bind().execute(
        sa.text(
            f"""
            SELECT
                count(*) FILTER (WHERE length(name_ru) > 200) AS name_ru_too_long,
                count(*) FILTER (WHERE length(name_he) > 200) AS name_he_too_long,
                count(*) FILTER (WHERE length(install_type) > 120) AS install_type_too_long,
                count(*) FILTER (WHERE manufacturer IS NOT NULL AND length(manufacturer) > 200)
                    AS manufacturer_too_long,
                count(*) FILTER (WHERE unit NOT IN ('pcs', 'piece', 'set', 'point'))
                    AS invalid_unit,
                count(*) FILTER (WHERE upper(status) NOT IN ('ACTIVE', 'ARCHIVED'))
                    AS invalid_status
            FROM {LEGACY_TABLE}
            """
        )
    ).mappings().one()
    failures = [name for name, count in invalid.items() if int(count or 0) > 0]
    if failures:
        raise RuntimeError(
            "Legacy product_library contains values incompatible with the canonical "
            f"schema: {', '.join(failures)}"
        )


def _copy_legacy_rows_to_canonical() -> None:
    _validate_legacy_upgrade_rows()
    op.execute(
        sa.text(
            f"""
            INSERT INTO {CANONICAL_TABLE} (
                id, created_at, updated_at, company_id, sku, name_ru, name_he,
                install_type, manufacturer, unit, status
            )
            SELECT
                id, created_at, updated_at, company_id, sku, name_ru, name_he,
                install_type, manufacturer,
                CASE WHEN unit IN ('pcs', 'piece') THEN 'piece' ELSE unit END,
                upper(status)
            FROM {LEGACY_TABLE}
            """
        )
    )


def _validate_canonical_downgrade_rows() -> None:
    invalid = op.get_bind().execute(
        sa.text(
            f"""
            SELECT
                count(*) FILTER (WHERE length(name_ru) > 255) AS name_ru_too_long,
                count(*) FILTER (WHERE length(name_he) > 255) AS name_he_too_long,
                count(*) FILTER (WHERE length(install_type) > 80) AS install_type_too_long,
                count(*) FILTER (WHERE manufacturer IS NOT NULL AND length(manufacturer) > 255)
                    AS manufacturer_too_long
            FROM {CANONICAL_TABLE}
            """
        )
    ).mappings().one()
    failures = [name for name, count in invalid.items() if int(count or 0) > 0]
    if failures:
        raise RuntimeError(
            "Canonical product library cannot be restored to the legacy schema: "
            f"{', '.join(failures)}"
        )


def _copy_canonical_rows_to_legacy() -> None:
    _validate_canonical_downgrade_rows()
    op.execute(
        sa.text(
            f"""
            INSERT INTO {LEGACY_TABLE} (
                id, created_at, updated_at, company_id, sku, name_ru, name_he,
                install_type, manufacturer, unit, status
            )
            SELECT
                id, created_at, updated_at, company_id, sku, name_ru, name_he,
                install_type, manufacturer,
                CASE WHEN unit = 'piece' THEN 'pcs' ELSE unit END,
                status
            FROM {CANONICAL_TABLE}
            ON CONFLICT (company_id, sku) DO UPDATE SET
                name_ru = EXCLUDED.name_ru,
                name_he = EXCLUDED.name_he,
                install_type = EXCLUDED.install_type,
                manufacturer = EXCLUDED.manufacturer,
                unit = EXCLUDED.unit,
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
            """
        )
    )


def upgrade() -> None:
    if _has_table(CANONICAL_TABLE):
        return

    has_legacy_table = _has_table(LEGACY_TABLE)
    if has_legacy_table:
        _rename_legacy_relations()

    op.create_table(
        CANONICAL_TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(80), nullable=False),
        sa.Column("name_ru", sa.String(200), nullable=False),
        sa.Column("name_he", sa.String(200), nullable=False),
        sa.Column("install_type", sa.String(120), nullable=False),
        sa.Column("manufacturer", sa.String(200), nullable=True),
        sa.Column("unit", sa.String(20), nullable=False, server_default="piece"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_product_library_company_id_companies",
        ),
        sa.UniqueConstraint("company_id", "sku", name="uq_product_library_company_sku"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_product_library_status",
        ),
        sa.CheckConstraint(
            "unit IN ('piece', 'set', 'point')",
            name="ck_product_library_unit",
        ),
    )
    op.create_index("ix_product_library_items_company_id", "product_library_items", ["company_id"])
    op.create_index(
        "ix_product_library_company_status",
        "product_library_items",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_product_library_install_type",
        "product_library_items",
        ["company_id", "install_type"],
    )
    if has_legacy_table:
        _copy_legacy_rows_to_canonical()


def downgrade() -> None:
    if not _has_table(CANONICAL_TABLE):
        return

    if _has_table(LEGACY_TABLE):
        _copy_canonical_rows_to_legacy()
        op.drop_table(CANONICAL_TABLE)
        _restore_legacy_relation_names()
        return

    op.drop_table(CANONICAL_TABLE)
