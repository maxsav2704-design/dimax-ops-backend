"""Check earning evidence only in the guarded, empty disposable migration database."""
import os
from decimal import Decimal
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from scripts.db_factory_price_timeline_migration_smoke import main as verify_timeline


def main():
    if os.getenv("DIMAX_FACTORY_EARNINGS_MIGRATION") != "1":
        raise RuntimeError("Explicit factory earning migration check required")
    # Enforces test environment, exact isolated database/host and an initially empty database.
    verify_timeline()
    from app.modules.doors.application.commands import MarkDoorInstalled
    from app.modules.doors.application.use_cases import DoorUseCases
    from app.modules.doors.infrastructure.models import DoorORM
    from app.modules.earnings.infrastructure.factory_price_models import FactoryEarningPriceORM
    from app.modules.earnings.infrastructure.models import CompletedWorkORM
    from app.modules.rates.infrastructure.timeline_models import FactoryPriceActivationORM
    from app.shared.infrastructure.db.base import Base, utcnow
    from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

    engine = create_engine(os.environ["DATABASE_URL"])
    config = Config("alembic.ini")
    tables = [name for name in inspect(engine).get_table_names() if name != "alembic_version"]
    def snapshot(names):
        with engine.connect() as connection:
            return {name: connection.execute(text(
                f'SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), \'[]\'::jsonb) FROM "{name}" t'
            )).scalar_one() for name in names}
    before = snapshot(tables)
    command.upgrade(config, "0066_factory_earning_prices")
    assert snapshot(tables) == before
    def include_object(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name in {"factory_earning_prices", "completed_work", "factory_price_list_items",
                            "factory_price_activations", "sync_queue_items"}
        return obj.table.name == "factory_earning_prices" or name in {
            "uq_completed_work_tenant_id", "uq_factory_price_items_tenant_list_id",
            "uq_factory_activation_tenant_id", "client_happened_at"}
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"include_object": include_object})
        assert compare_metadata(context, Base.metadata) == []
        assert connection.execute(text("SELECT count(*) FROM factory_earning_prices")).scalar_one() == 0
    command.downgrade(config, "0065_factory_price_timeline")
    assert "factory_earning_prices" not in inspect(engine).get_table_names()
    assert snapshot(tables) == before
    command.upgrade(config, "0066_factory_earning_prices")
    assert snapshot(tables) == before

    def assert_downgrade_blocked():
        all_tables = tables + ["factory_earning_prices"]
        with_history = snapshot(all_tables)
        try:
            command.downgrade(config, "0065_factory_price_timeline")
        except RuntimeError as error:
            assert "factory earning evidence or offline execution times exist" in str(error)
        else:
            raise AssertionError("Downgrade discarded earning evidence")
        assert snapshot(all_tables) == with_history
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0066_factory_earning_prices"

    with Session(engine) as session:
        old_door = session.scalar(select(DoorORM))
        activation = session.scalar(select(FactoryPriceActivationORM))
        company_id, actor = old_door.company_id, activation.created_by
        session.execute(text("""INSERT INTO sync_queue_items
            (id, company_id, user_id, device_id, project_id, entity_type, entity_id, operation_type,
             payload, base_version, status, created_at, client_happened_at)
            VALUES (:id, :cid, :uid, 'migration-qa', :pid, 'door', :did, 'DOOR_SET_STATUS',
                    '{}', 0, 'CONFLICT', :at, :at)"""),
            {"id": uuid4(), "cid": company_id, "uid": actor, "pid": old_door.project_id,
             "did": old_door.id, "at": utcnow()})
        session.commit()
    assert_downgrade_blocked()
    with Session(engine) as session:
        # Only the disposable fixture is removed to independently exercise the evidence guard.
        session.execute(text("DELETE FROM sync_queue_items WHERE device_id='migration-qa' AND company_id=:cid"), {"cid": company_id})
        old_door = session.scalar(select(DoorORM))
        door = DoorORM(company_id=company_id, project_id=old_door.project_id, door_type_id=old_door.door_type_id,
            installer_id=old_door.installer_id, unit_label="QA-NEW", our_price=Decimal("500"),
            status="NOT_INSTALLED", is_locked=False)
        session.add(door)
        session.commit()
        door_id = door.id
    with SqlAlchemyUnitOfWork() as uow:
        DoorUseCases.mark_installed(uow, MarkDoorInstalled(company_id, actor, door_id))
    with Session(engine) as session:
        new_work = session.scalar(select(CompletedWorkORM).where(CompletedWorkORM.door_id == door_id))
        assert new_work.amount_snapshot == Decimal("300")
        assert session.get(FactoryEarningPriceORM, new_work.id).confirmed_rate == Decimal("300")
        old_work = session.scalar(select(CompletedWorkORM).where(CompletedWorkORM.door_id != door_id))
        assert old_work.amount_snapshot == Decimal("250")
        assert session.get(FactoryEarningPriceORM, old_work.id) is None
    assert_downgrade_blocked()
    engine.dispose()
    print("PASS: factory earnings upgrade/rollback/metadata, unchanged legacy data, real completion and both downgrade guards")


if __name__ == "__main__":
    main()
