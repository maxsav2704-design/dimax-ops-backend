"""Run only against an explicitly named empty disposable database."""
import os
from datetime import timedelta
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def main():
    url = make_url(os.environ["DATABASE_URL"])
    if (os.getenv("APP_ENV") != "test" or os.getenv("DIMAX_MAILBOX_MIGRATION") != "1"
            or url.host != "db" or url.database != "dimax_factory_mailbox_migrations_20261010"):
        raise RuntimeError("Requires the explicitly enabled disposable mailbox migration database")
    engine = create_engine(url)
    if inspect(engine).get_table_names():
        raise RuntimeError("Migration check requires an empty disposable database")
    config = Config("alembic.ini")
    command.upgrade(config, "0068_ai_memory")
    from app.modules.identity.infrastructure.models import CompanyORM, UserORM
    from app.modules.rates.infrastructure.price_list_models import FactoryPriceListORM
    from app.shared.infrastructure.db.base import Base, utcnow
    now = utcnow()
    cid, uid, pid, aid = [uuid4() for _ in range(4)]
    with Session(engine) as session:
        session.add(CompanyORM(id=cid, name="Mailbox migration QA", is_active=True))
        session.flush()
        session.add(UserORM(id=uid, company_id=cid, email="migration@example.test", full_name="QA Admin",
                           role="ADMIN", password_hash="not-a-login-credential", is_active=True, status="ACTIVE"))
        session.flush()
        session.add(FactoryPriceListORM(id=pid, company_id=cid, version=1, request_id=uuid4(),
                    request_fingerprint="0" * 64, reason="QA offer", agreement_reference="QA only",
                    created_by=uid, status="CONFIRMED"))
        session.flush()
        table = Table("factory_price_approvals", MetaData(), autoload_with=engine)
        session.execute(table.insert().values(id=aid, company_id=cid, price_list_id=pid, created_by=uid,
            token_hash="1" * 64, snapshot_hash="2" * 64, snapshot={}, factory_name="QA Factory",
            recipient_name="QA Representative", recipient_email="qa@example.com", created_at=now,
            updated_at=now, expires_at=now + timedelta(days=1), confirmed_at=now, confirmed_name="Legacy signer"))
        session.commit()
    # Explicit old-column projections also detect accidental changes to legacy decisions.
    tables = [Table(name, MetaData(), autoload_with=engine) for name in inspect(engine).get_table_names()
              if name != "alembic_version"]
    def snapshot():
        with engine.connect() as connection:
            return {table.name: sorted((dict(row) for row in connection.execute(select(table)).mappings()), key=str)
                    for table in tables}
    before = snapshot()
    command.upgrade(config, "head")
    assert snapshot() == before
    with engine.connect() as connection:
        assert connection.execute(text("SELECT mailbox_verified_at FROM factory_price_approvals")).scalar_one() is None
        context = MigrationContext.configure(connection, opts={"include_object":
            lambda obj, name, type_, reflected, compare_to: name == "factory_price_approvals" if type_ == "table"
            else obj.table.name == "factory_price_approvals" and name != "uq_factory_approvals_tenant_list_id"})
        assert compare_metadata(context, Base.metadata) == []
    command.downgrade(config, "0068_ai_memory")
    assert snapshot() == before
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.execute(text("UPDATE factory_price_approvals SET mailbox_requests=1 WHERE id=:id"), {"id": aid})
    try:
        command.downgrade(config, "0068_ai_memory")
    except RuntimeError as error:
        assert "verification history" in str(error)
    else:
        raise AssertionError("Downgrade erased a used verification budget")
    assert snapshot() == before
    engine.dispose()
    print("PASS: fresh chain, legacy decisions unchanged, no invented verification, metadata, rollback/re-upgrade and history guard")


if __name__ == "__main__":
    main()
