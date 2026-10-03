"""Check factory price-list migrations only in the explicitly named disposable QA DB."""
import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def main():
    url = make_url(os.environ["DATABASE_URL"])
    if (os.getenv("APP_ENV") != "test" or os.getenv("DIMAX_PRICE_LIST_MIGRATION") != "1"
            or url.host != "db" or url.database != "dimax_factory_price_migrations"):
        raise RuntimeError("Requires the explicitly enabled, isolated factory price migration database")
    engine = create_engine(url)
    if inspect(engine).get_table_names():
        raise RuntimeError("Migration check requires an empty disposable database")
    config = Config("alembic.ini")
    command.upgrade(config, "0062_issue_sync")
    from app.modules.identity.infrastructure.models import CompanyORM, UserORM
    from app.modules.door_types.infrastructure.models import DoorTypeORM
    from app.modules.installers.infrastructure.models import InstallerORM
    from app.modules.projects.infrastructure.models import ProjectORM
    from app.modules.doors.infrastructure.models import DoorORM
    from app.modules.rates.infrastructure.models import InstallerRateORM
    from app.modules.earnings.infrastructure.models import CompletedWorkORM
    from app.modules.rates.infrastructure.price_list_models import FactoryPriceListORM
    from app.shared.infrastructure.db.base import Base

    cid, uid, tid, iid, pid, did = [uuid4() for _ in range(6)]
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(CompanyORM(id=cid, name="QA migration only", is_active=True))
        session.flush()
        session.add_all([
            UserORM(id=uid, company_id=cid, email="migration@example.test", full_name="QA Admin",
                    role="ADMIN", password_hash="not-a-login-credential", is_active=True, status="ACTIVE"),
            DoorTypeORM(id=tid, company_id=cid, name="Entrance", code="ENTRY"),
            InstallerORM(id=iid, company_id=cid, full_name="QA Installer", is_active=True, status="ACTIVE"),
            ProjectORM(id=pid, company_id=cid, name="QA Project", address="QA Address", status="OK"),
        ])
        session.flush()
        session.add_all([
            DoorORM(id=did, company_id=cid, project_id=pid, door_type_id=tid, installer_id=iid,
                    unit_label="A-101", our_price=Decimal("500"), status="INSTALLED", is_locked=True),
            InstallerRateORM(company_id=cid, installer_id=iid, door_type_id=tid, price=Decimal("250")),
        ])
        session.flush()
        session.add(CompletedWorkORM(company_id=cid, project_id=pid, door_id=did, installer_id=iid,
                    completed_at=now, quantity=Decimal("1"), rate_snapshot=Decimal("250"), amount_snapshot=Decimal("250")))
        session.commit()

    legacy_tables = [name for name in inspect(engine).get_table_names() if name != "alembic_version"]

    def snapshot():
        with engine.connect() as connection:
            return {name: connection.execute(text(
                f'SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), \'[]\'::jsonb) FROM "{name}" t'
            )).scalar_one() for name in legacy_tables}

    before = snapshot()
    command.upgrade(config, "0063_factory_price_lists")
    assert snapshot() == before
    new_tables = {"factory_price_lists", "factory_price_list_items"}
    with engine.connect() as connection:
        for name in new_tables:
            assert connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() == 0
        context = MigrationContext.configure(connection, opts={
            "include_object": lambda obj, name, type_, reflected, compare_to:
                name in new_tables if type_ == "table" else (
                    obj.table.name in new_tables and name != "uq_factory_price_items_tenant_list_id"),
        })
        assert compare_metadata(context, Base.metadata) == []
    command.downgrade(config, "0062_issue_sync")
    assert not new_tables.intersection(inspect(engine).get_table_names())
    assert snapshot() == before
    command.upgrade(config, "0063_factory_price_lists")
    assert snapshot() == before
    with Session(engine) as session:
        session.add(FactoryPriceListORM(company_id=cid, version=1, request_id=uuid4(),
                    request_fingerprint="0" * 64, reason="QA offer", agreement_reference="QA only", created_by=uid))
        session.commit()
    try:
        command.downgrade(config, "0062_issue_sync")
    except RuntimeError as error:
        assert "history exists" in str(error)
    else:
        raise AssertionError("Downgrade discarded price-list history")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM factory_price_lists")).scalar_one() == 1
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0063_factory_price_lists"
    assert snapshot() == before
    engine.dispose()
    print("PASS: empty -> 0062 -> 0063 -> 0062 -> 0063; legacy data unchanged, metadata matches, no automatic approvals, history rollback protected")


if __name__ == "__main__":
    main()
