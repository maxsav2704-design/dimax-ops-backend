"""Verify invitation migration only in the guarded disposable factory QA database."""
import os
from datetime import timedelta

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from scripts.db_factory_price_list_migration_smoke import main as verify_drafts


def main():
    if os.getenv("DIMAX_PRICE_APPROVAL_MIGRATION") != "1":
        raise RuntimeError("Explicit factory approval migration check required")
    # The preceding check enforces APP_ENV, the exact database host/name and an empty database.
    verify_drafts()
    from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
    from app.modules.rates.infrastructure.price_list_models import FactoryPriceListORM
    from app.shared.infrastructure.db.base import Base, utcnow
    engine = create_engine(os.environ["DATABASE_URL"])
    config = Config("alembic.ini")
    tables = [name for name in inspect(engine).get_table_names() if name != "alembic_version"]
    def snapshot():
        with engine.connect() as connection:
            return {name: connection.execute(text(
                f'SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), \'[]\'::jsonb) FROM "{name}" t'
            )).scalar_one() for name in tables}
    before = snapshot()
    command.upgrade(config, "0064_factory_price_approval")
    assert snapshot() == before
    new_tables = {"factory_price_approvals", "factory_price_lists", "factory_price_list_items"}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM factory_price_approvals")).scalar_one() == 0
        context = MigrationContext.configure(connection, opts={
            "include_object": lambda obj, name, type_, reflected, compare_to:
                name in new_tables if type_ == "table" else obj.table.name in new_tables,
        })
        assert compare_metadata(context, Base.metadata) == []
    command.downgrade(config, "0063_factory_price_lists")
    assert "factory_price_approvals" not in inspect(engine).get_table_names()
    assert snapshot() == before
    command.upgrade(config, "0064_factory_price_approval")
    with Session(engine) as session:
        price_list = session.scalar(select(FactoryPriceListORM))
        now = utcnow()
        session.add(FactoryPriceApprovalORM(company_id=price_list.company_id, price_list_id=price_list.id,
            created_by=price_list.created_by, token_hash="1" * 64, snapshot_hash="2" * 64, snapshot={},
            factory_name="QA Factory", recipient_name="QA Recipient", recipient_email="qa@example.com",
            created_at=now, expires_at=now + timedelta(hours=1)))
        session.commit()
    try:
        command.downgrade(config, "0063_factory_price_lists")
    except RuntimeError as error:
        assert "history exists" in str(error)
    else:
        raise AssertionError("Downgrade discarded factory invitation history")
    assert snapshot() == before
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM factory_price_approvals")).scalar_one() == 1
    engine.dispose()
    print("PASS: factory approval upgrade, rollback, metadata, legacy snapshots and history protection")


if __name__ == "__main__":
    main()
