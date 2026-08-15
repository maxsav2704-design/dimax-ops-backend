from __future__ import annotations

import os
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


COMPANY_ID = uuid.UUID("00000000-0000-0000-0000-000000000049")
LEGACY_PRODUCT_ID = uuid.UUID("00000000-0000-0000-0000-000000004901")
NEW_PRODUCT_ID = uuid.UUID("00000000-0000-0000-0000-000000004902")
PRICE_ID = uuid.UUID("00000000-0000-0000-0000-000000004903")
LEGACY_REVISION = "0048_users_email_citext"
HEAD_REVISION = "0057_payroll_correction_uq"


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def _assert_enabled() -> None:
    if os.getenv("DIMAX_LEGACY_MIGRATION_SMOKE") != "1":
        raise RuntimeError(
            "Refusing to mutate a database without DIMAX_LEGACY_MIGRATION_SMOKE=1"
        )


def _current_revision(connection) -> str:
    return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _assert_revision(connection, expected: str) -> None:
    actual = _current_revision(connection)
    if actual != expected:
        raise AssertionError(f"Expected Alembic revision {expected}, got {actual}")


def _table_exists(connection, table_name: str) -> bool:
    return connection.execute(
        text("SELECT to_regclass(:table_name) IS NOT NULL"),
        {"table_name": f"public.{table_name}"},
    ).scalar_one()


def _prepare_legacy_fixture(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            _assert_revision(connection, LEGACY_REVISION)
            if _table_exists(connection, "product_library") or _table_exists(
                connection, "product_library_items"
            ):
                raise AssertionError("Legacy fixture requires both product library tables to be absent")

            connection.execute(
                text(
                    """
                    INSERT INTO companies (id, created_at, updated_at, name, is_active)
                    VALUES (:company_id, now(), now(), 'Legacy Migration Smoke', true)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"company_id": COMPANY_ID},
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE product_library (
                        id uuid PRIMARY KEY,
                        company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                        sku varchar(80) NOT NULL,
                        name_ru varchar(255) NOT NULL,
                        name_he varchar(255) NOT NULL,
                        install_type varchar(80) NOT NULL,
                        manufacturer varchar(255),
                        unit varchar(32) NOT NULL DEFAULT 'pcs',
                        status varchar(20) NOT NULL DEFAULT 'ACTIVE',
                        created_at timestamptz NOT NULL DEFAULT now(),
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        CONSTRAINT uq_product_library_company_sku UNIQUE (company_id, sku),
                        CONSTRAINT ck_product_library_status
                            CHECK (status IN ('ACTIVE', 'ARCHIVED'))
                    )
                    """
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_product_library_items_company_id "
                    "ON product_library (company_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_product_library_company_status "
                    "ON product_library (company_id, status)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_product_library_install_type "
                    "ON product_library (company_id, install_type)"
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE client_price_list (
                        id uuid PRIMARY KEY,
                        company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                        product_id uuid NOT NULL REFERENCES product_library(id) ON DELETE CASCADE,
                        base_client_rate numeric(12, 2) NOT NULL,
                        final_client_rate numeric(12, 2) NOT NULL,
                        effective_from date NOT NULL,
                        effective_to date,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        CONSTRAINT ck_client_price_list_rates_nonnegative
                            CHECK (base_client_rate >= 0 AND final_client_rate >= 0)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_client_price_list_product_effective "
                    "ON client_price_list (product_id, effective_from DESC)"
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO product_library (
                        id, company_id, sku, name_ru, name_he, install_type,
                        manufacturer, unit, status
                    ) VALUES (
                        :product_id, :company_id, 'LEGACY-49', 'Legacy RU',
                        'Legacy HE', 'door', 'DIMAX', 'pcs', 'ACTIVE'
                    )
                    """
                ),
                {"product_id": LEGACY_PRODUCT_ID, "company_id": COMPANY_ID},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO client_price_list (
                        id, company_id, product_id, base_client_rate,
                        final_client_rate, effective_from
                    ) VALUES (
                        :price_id, :company_id, :product_id, 100.00, 125.00,
                        DATE '2026-01-01'
                    )
                    """
                ),
                {
                    "price_id": PRICE_ID,
                    "company_id": COMPANY_ID,
                    "product_id": LEGACY_PRODUCT_ID,
                },
            )
    finally:
        engine.dispose()


def _relation_names(connection, table_name: str) -> set[str]:
    return set(
        connection.execute(
            text(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_index i ON i.indexrelid = c.oid
                WHERE i.indrelid = to_regclass(:table_name)
                """
            ),
            {"table_name": f"public.{table_name}"},
        ).scalars()
    )


def _constraint_names(connection, table_name: str) -> set[str]:
    return set(
        connection.execute(
            text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = to_regclass(:table_name)
                """
            ),
            {"table_name": f"public.{table_name}"},
        ).scalars()
    )


def _verify_upgrade(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            _assert_revision(connection, HEAD_REVISION)
            assert _table_exists(connection, "product_library")
            assert _table_exists(connection, "product_library_items")

            legacy = connection.execute(
                text(
                    "SELECT id, sku, unit, status FROM product_library_items "
                    "WHERE id = :product_id"
                ),
                {"product_id": LEGACY_PRODUCT_ID},
            ).mappings().one()
            assert legacy["sku"] == "LEGACY-49"
            assert legacy["unit"] == "piece"
            assert legacy["status"] == "ACTIVE"

            assert "uq_product_library_legacy_company_sku" in _constraint_names(
                connection, "product_library"
            )
            assert "uq_product_library_company_sku" in _constraint_names(
                connection, "product_library_items"
            )
            legacy_indexes = _relation_names(connection, "product_library")
            assert "ix_product_library_legacy_company_id" in legacy_indexes
            assert "ix_product_library_legacy_company_status" in legacy_indexes
            assert "ix_product_library_legacy_install_type" in legacy_indexes

            fk_target = connection.execute(
                text(
                    """
                    SELECT confrelid::regclass::text
                    FROM pg_constraint
                    WHERE conrelid = 'client_price_list'::regclass
                      AND contype = 'f'
                      AND conname = 'client_price_list_product_id_fkey'
                    """
                )
            ).scalar_one()
            assert fk_target == "product_library"

            connection.execute(
                text(
                    """
                    INSERT INTO product_library_items (
                        id, company_id, sku, name_ru, name_he, install_type,
                        manufacturer, unit, status
                    ) VALUES (
                        :product_id, :company_id, 'NEW-49', 'New RU', 'New HE',
                        'technical', NULL, 'set', 'ACTIVE'
                    )
                    ON CONFLICT (company_id, sku) DO NOTHING
                    """
                ),
                {"product_id": NEW_PRODUCT_ID, "company_id": COMPANY_ID},
            )
    finally:
        engine.dispose()


def _verify_downgrade(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            _assert_revision(connection, LEGACY_REVISION)
            assert _table_exists(connection, "product_library")
            assert not _table_exists(connection, "product_library_items")

            rows = connection.execute(
                text(
                    "SELECT id, sku, unit FROM product_library "
                    "WHERE id IN (:legacy_id, :new_id) ORDER BY sku"
                ),
                {"legacy_id": LEGACY_PRODUCT_ID, "new_id": NEW_PRODUCT_ID},
            ).mappings().all()
            assert len(rows) == 2
            by_sku = {row["sku"]: row for row in rows}
            assert by_sku["LEGACY-49"]["unit"] == "pcs"
            assert by_sku["NEW-49"]["unit"] == "set"

            assert "uq_product_library_company_sku" in _constraint_names(
                connection, "product_library"
            )
            legacy_indexes = _relation_names(connection, "product_library")
            assert "ix_product_library_items_company_id" in legacy_indexes
            assert "ix_product_library_company_status" in legacy_indexes
            assert "ix_product_library_install_type" in legacy_indexes

            price_product_id = connection.execute(
                text("SELECT product_id FROM client_price_list WHERE id = :price_id"),
                {"price_id": PRICE_ID},
            ).scalar_one()
            assert price_product_id == LEGACY_PRODUCT_ID
    finally:
        engine.dispose()


def main() -> int:
    _assert_enabled()
    database_url = _database_url()
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, LEGACY_REVISION)
    _prepare_legacy_fixture(database_url)
    command.upgrade(alembic_config, "head")
    _verify_upgrade(database_url)
    command.downgrade(alembic_config, LEGACY_REVISION)
    _verify_downgrade(database_url)
    command.upgrade(alembic_config, "head")
    _verify_upgrade(database_url)

    print(
        "[legacy-product-library-migration] OK: "
        "upgrade/downgrade preserved legacy and canonical rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
