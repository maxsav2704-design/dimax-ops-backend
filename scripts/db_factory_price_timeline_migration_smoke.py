"""Verify the price timeline only in the guarded disposable factory migration database."""
import os
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text

from scripts.db_factory_price_approval_migration_smoke import main as verify_approvals


def main():
    if os.getenv("DIMAX_PRICE_TIMELINE_MIGRATION") != "1":
        raise RuntimeError("Explicit factory timeline migration check required")
    # Includes the exact isolated host/name, empty-DB and explicit test-environment guards.
    verify_approvals()
    from app.shared.infrastructure.db.base import Base, utcnow

    engine = create_engine(os.environ["DATABASE_URL"])
    config = Config("alembic.ini")
    tables = [name for name in inspect(engine).get_table_names() if name != "alembic_version"]
    def snapshot(names):
        with engine.connect() as connection:
            return {name: connection.execute(text(
                f'SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), \'[]\'::jsonb) FROM "{name}" t'
            )).scalar_one() for name in names}
    before = snapshot(tables)
    command.upgrade(config, "0065_factory_price_timeline")
    assert snapshot(tables) == before
    def include_object(obj, name, type_, reflected, compare_to):
        if name == "uq_factory_activation_tenant_id":
            return False
        if type_ == "table":
            return name in {"factory_price_activations", "factory_price_approvals"}
        return obj.table.name == "factory_price_activations" or (
            type_ == "unique_constraint" and name == "uq_factory_approvals_tenant_list_id")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM factory_price_activations")).scalar_one() == 0
        context = MigrationContext.configure(connection, opts={"include_object": include_object})
        assert compare_metadata(context, Base.metadata) == []
    command.downgrade(config, "0064_factory_price_approval")
    assert "factory_price_activations" not in inspect(engine).get_table_names()
    assert snapshot(tables) == before
    command.upgrade(config, "0065_factory_price_timeline")
    assert snapshot(tables) == before

    business_tables = [name for name in tables if not name.startswith("factory_price_")
                       and name not in {"audit_logs", "admin_profiles"}]
    business_before = snapshot(business_tables)
    # Historical schema fixtures must not call current services, which require later migrations.
    # The complete authorization/activation/quote flow is covered by integration tests at head.
    metadata = MetaData()
    approvals = Table("factory_price_approvals", metadata, autoload_with=engine)
    prices = Table("factory_price_lists", metadata, autoload_with=engine)
    activations = Table("factory_price_activations", metadata, autoload_with=engine)
    with engine.begin() as connection:
        approval = connection.execute(select(approvals)).mappings().one()
        now = utcnow()
        connection.execute(approvals.update().where(approvals.c.id == approval["id"]).values(
            confirmed_at=now, confirmed_name="QA historical fixture"))
        connection.execute(prices.update().where(prices.c.id == approval["price_list_id"]).values(status="CONFIRMED"))
        connection.execute(activations.insert().values(
            id=uuid4(), company_id=approval["company_id"], price_list_id=approval["price_list_id"],
            approval_id=approval["id"], request_id=uuid4(), request_fingerprint="3" * 64,
            snapshot_hash=approval["snapshot_hash"], effective_from=now, created_at=now, updated_at=now,
            created_by=approval["created_by"], reason="QA history preservation at schema 0065"))
    assert snapshot(business_tables) == business_before
    all_tables = tables + ["factory_price_activations"]
    with_history = snapshot(all_tables)
    try:
        command.downgrade(config, "0064_factory_price_approval")
    except RuntimeError as error:
        assert "effective factory price history exists" in str(error)
    else:
        raise AssertionError("Downgrade discarded effective price history")
    assert snapshot(all_tables) == with_history
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0065_factory_price_timeline"
    engine.dispose()
    print("PASS: timeline upgrade, rollback, metadata, historical activation fixture, legacy business snapshots and history protection")


if __name__ == "__main__":
    main()
