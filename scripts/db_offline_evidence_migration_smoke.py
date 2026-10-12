"""Exercise 0071 on historical fixtures, only in a new disposable QA database."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Boolean, DateTime, MetaData, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


DATABASE = "dimax_offline_evidence_migration_tests"
PREVIOUS = "0070_factory_contact"
REVISION = "0071_offline_evidence"
EVIDENCE_COLUMNS = {
    "doors": "assignment_started_at",
    "sync_events": "client_time_has_timezone",
    "sync_queue_items": "client_time_has_timezone",
}


def _validated_database_url():
    if os.getenv("APP_ENV") != "test" or os.getenv("DIMAX_OFFLINE_EVIDENCE_MIGRATION") != "1":
        raise RuntimeError("Explicit test-only offline migration check required")
    try:
        url = make_url(os.environ.get("DATABASE_URL", ""))
    except (ArgumentError, ValueError):
        raise RuntimeError("Invalid test database URL") from None
    if (url.drivername != "postgresql+psycopg2" or url.host != "db"
            or url.database != DATABASE or url.port not in (None, 5432) or url.query):
        raise RuntimeError("Requires the exact isolated offline migration database on db:5432")
    return url


def _require_empty_database(connection):
    if connection.execute(text("SELECT current_database()")).scalar_one() != DATABASE:
        raise RuntimeError("Connected to a different database; refusing migration")
    occupied = connection.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp_%'
        ) OR EXISTS (
            SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE t.typtype = 'e' AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        ) OR EXISTS (
            SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
        )
    """)).scalar_one()
    if occupied:
        raise RuntimeError("Requires an empty disposable database; existing objects will not be removed")


def _tables(engine):
    metadata = MetaData()
    metadata.reflect(bind=engine)
    return metadata.tables


def _snapshot(engine, tables):
    # The reflected column set lets us compare every pre-migration column unchanged.
    quote = engine.dialect.identifier_preparer.quote
    with engine.connect() as connection:
        return {name: connection.execute(text(
            "SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb) "
            f"FROM (SELECT {', '.join(quote(c.name) for c in table.columns)} FROM {quote(name)}) t"
        )).scalar_one() for name, table in tables.items()}


def _seed_history(engine, tables):
    at = datetime.now(timezone.utc) - timedelta(days=3)
    fixtures = []
    with engine.begin() as connection:
        def insert(name, **values):
            table = tables[name]
            row = {"id": uuid4(), **values}
            for column in ("created_at", "updated_at"):
                if column in table.c:
                    row.setdefault(column, at)
            connection.execute(table.insert().values(**row))
            return row

        for tenant in ("A", "B"):
            company = insert("companies", name=f"Offline migration QA {tenant}", is_active=True)
            common = {"company_id": company["id"]}
            user = insert("users", **common, email=f"migration-{tenant}@example.test",
                full_name="QA Installer", role="INSTALLER", password_hash="not-a-login-credential",
                is_active=True, status="ACTIVE")
            installer = insert("installers", **common, user_id=user["id"], full_name="QA Installer",
                is_active=True, status="ACTIVE")
            alternate = insert("installers", **common, full_name="QA Alternate", is_active=True, status="ACTIVE")
            kind = insert("door_types", **common, code="ENTRY", name="Entrance", is_active=True,
                is_critical_default=False)
            projects = [insert("projects", **common, name=f"QA {tenant}-{index}", address="QA only",
                status="OK", lifecycle_status="ACTIVE", health_status="NORMAL") for index in (1, 2)]
            door_values = {**common, "project_id": projects[0]["id"], "door_type_id": kind["id"],
                "installer_id": installer["id"], "our_price": Decimal("500.00"),
                "installer_rate_snapshot": Decimal("250.00"), "apply_surcharge_to_installer": False,
                "is_critical": False, "surcharge_pct": Decimal("100.00")}
            installed = insert("doors", **door_values, unit_label="A-101", status="INSTALLED",
                is_locked=True, installed_at=at + timedelta(days=1), version=5)
            pending = insert("doors", **door_values, unit_label="A-102", status="IN_PROGRESS",
                is_locked=False, version=4)
            unassigned = insert("doors", **{**door_values, "installer_id": None},
                unit_label="A-103", status="NOT_INSTALLED", is_locked=False, version=0)
            work = insert("completed_work", **common, project_id=projects[0]["id"], door_id=installed["id"],
                installer_id=installer["id"], completed_at=at + timedelta(days=1), quantity=Decimal("1.00"),
                rate_snapshot=Decimal("250.00"), amount_snapshot=Decimal("250.00"),
                work_kind="DOOR", entry_type="ORIGINAL")
            insert("client_price_snapshots", **common, completed_work_id=work["id"],
                base_client_rate=Decimal("500.00"), final_client_rate=Decimal("500.00"),
                final_installer_rate=Decimal("250.00"))
            event_ids, queue_ids = [], []
            for status in ("PENDING", "CONFLICT", "APPLIED", "BLOCKED"):
                happened = None if status == "BLOCKED" else at + timedelta(days=1)
                payload = {"door_id": str(pending["id"]), "status": "INSTALLED", "base_version": 4}
                event = insert("sync_events", **common, installer_id=installer["id"],
                    project_id=projects[0]["id"], event_type="DOOR_SET_STATUS", client_event_id=str(uuid4()),
                    client_happened_at=happened, payload=payload,
                    apply_error="CONFLICT_FACTORY_PRICE" if status in ("CONFLICT", "BLOCKED") else None,
                    applied_at=at + timedelta(days=2) if status == "APPLIED" else None,
                    created_at=at + timedelta(days=2))
                queue = insert("sync_queue_items", **common, user_id=user["id"], device_id="migration-qa",
                    project_id=projects[0]["id"], entity_type="door", entity_id=pending["id"],
                    operation_type="DOOR_SET_STATUS", payload=payload, base_version=4, status=status,
                    client_happened_at=happened, created_at=at + timedelta(days=2),
                    conflict_code="CONFLICT_FACTORY_PRICE" if status in ("CONFLICT", "BLOCKED") else None,
                    synced_at=at + timedelta(days=2) if status == "APPLIED" else None)
                event_ids.append(event["id"])
                queue_ids.append(queue["id"])
            fixtures.append({"door_values": door_values, "pending": pending["id"],
                "unassigned": unassigned["id"], "alternate": alternate["id"],
                "other_project": projects[1]["id"], "event": event_ids[1], "queue": queue_ids[1]})
    return fixtures


def _assert_revision(engine, expected):
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == expected


def _assert_schema(engine):
    inspector = inspect(engine)
    for table, name in EVIDENCE_COLUMNS.items():
        column = next(c for c in inspector.get_columns(table) if c["name"] == name)
        assert column["nullable"] and column["default"] is None
        expected = DateTime if table == "doors" else Boolean
        assert isinstance(column["type"], expected)
        if table == "doors":
            assert column["type"].timezone
    with engine.connect() as connection:
        assert connection.execute(text("""SELECT t.tgenabled FROM pg_trigger t
            JOIN pg_proc p ON p.oid = t.tgfoid
            WHERE t.tgrelid = 'doors'::regclass AND t.tgname = 'door_assignment_boundary'
              AND p.proname = 'dimax_door_assignment_boundary'""")).scalar_one() == "O"
    _assert_revision(engine, REVISION)


def _assert_unknown_history(engine):
    with engine.connect() as connection:
        for table, column in EVIDENCE_COLUMNS.items():
            assert connection.execute(text(f'SELECT count(*) FROM "{table}" WHERE "{column}" IS NOT NULL')).scalar_one() == 0


def _verify_assignment_trigger(engine, tables, fixtures):
    door = tables["doors"]
    first, second = fixtures
    spoofed = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            def boundary(door_id):
                return connection.execute(select(door.c.assignment_started_at).where(door.c.id == door_id)).scalar_one()

            def change(door_id, **values):
                connection.execute(door.update().where(door.c.id == door_id).values(**values))

            def reassigned(door_id, **values):
                before = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                change(door_id, assignment_started_at=spoofed, **values)
                after = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                value = boundary(door_id)
                assert before <= value <= after
                return value

            change(first["pending"], assignment_started_at=spoofed, comment="Unrelated edit")
            assert boundary(first["pending"]) is None
            probe = first["unassigned"]
            value = reassigned(probe, installer_id=first["door_values"]["installer_id"])
            change(probe, assignment_started_at=spoofed, comment="Cannot backdate", version=1)
            assert boundary(probe) == value
            assert reassigned(probe, installer_id=first["alternate"]) >= value
            change(probe, installer_id=None, assignment_started_at=spoofed)
            assert boundary(probe) is None
            value = reassigned(probe, installer_id=first["door_values"]["installer_id"])
            assert reassigned(probe, project_id=first["other_project"]) >= value
            reassigned(probe, **second["door_values"])
            for installer_id in (None, first["door_values"]["installer_id"]):
                before = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                door_id = uuid4()
                connection.execute(door.insert().values(**{**first["door_values"], "installer_id": installer_id},
                    id=door_id, unit_label=str(door_id), status="NOT_INSTALLED", is_locked=False, version=0,
                    created_at=before, updated_at=before, assignment_started_at=spoofed))
                after = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                assert boundary(door_id) is None if installer_id is None else before <= boundary(door_id) <= after
        finally:
            transaction.rollback()


def _assert_downgrade_blocked(engine, config, tables):
    before = _snapshot(engine, tables)
    try:
        command.downgrade(config, PREVIOUS)
    except RuntimeError as error:
        assert "Cannot discard recorded offline execution evidence" in str(error)
    else:
        raise AssertionError("Downgrade discarded execution evidence")
    assert _snapshot(engine, tables) == before
    _assert_schema(engine)


def main():
    url = _validated_database_url()
    from app.core.config import settings

    if make_url(settings.DATABASE_URL) != url:
        raise RuntimeError("Alembic and the fixture must use the same isolated database")
    engine = create_engine(url, connect_args={"connect_timeout": 5,
        "options": "-c statement_timeout=30000 -c lock_timeout=5000"})
    try:
        with engine.connect() as connection:
            _require_empty_database(connection)
        config = Config("alembic.ini")
        command.upgrade(config, PREVIOUS)
        legacy = {name: table for name, table in _tables(engine).items() if name != "alembic_version"}
        fixtures = _seed_history(engine, legacy)
        before = _snapshot(engine, legacy)
        for _ in range(2):
            command.upgrade(config, REVISION)
            _assert_schema(engine)
            _assert_unknown_history(engine)
            assert _snapshot(engine, legacy) == before
            command.downgrade(config, PREVIOUS)
            _assert_revision(engine, PREVIOUS)
            for table, column in EVIDENCE_COLUMNS.items():
                assert column not in {c["name"] for c in inspect(engine).get_columns(table)}
            assert _snapshot(engine, legacy) == before
        command.upgrade(config, REVISION)
        current = _tables(engine)
        _verify_assignment_trigger(engine, current, fixtures)
        _assert_unknown_history(engine)
        assert _snapshot(engine, legacy) == before

        for name, key in (("sync_events", "event"), ("sync_queue_items", "queue")):
            table = current[name]
            for flag in (True, False):
                with engine.begin() as connection:
                    connection.execute(table.update().where(table.c.id == fixtures[0][key])
                        .values(client_time_has_timezone=flag))
                _assert_downgrade_blocked(engine, config, current)
                # Reset only this synthetic probe in the guarded disposable database.
                with engine.begin() as connection:
                    connection.execute(table.update().where(table.c.id == fixtures[0][key])
                        .values(client_time_has_timezone=None))
        probe = uuid4()
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(current["doors"].insert().values(**fixtures[0]["door_values"],
                id=probe, unit_label="NEW-ASSIGNMENT", status="NOT_INSTALLED", is_locked=False,
                version=0, created_at=now, updated_at=now))
        _assert_downgrade_blocked(engine, config, current)
        with engine.begin() as connection:
            connection.execute(current["doors"].delete().where(current["doors"].c.id == probe))
        assert _snapshot(engine, legacy) == before
        _assert_unknown_history(engine)
        _assert_schema(engine)
        print("PASS: 0070 -> 0071 historical two-tenant data preserved; unknown history not invented; "
              "assignment trigger verified; five evidence downgrade attempts refused atomically")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
