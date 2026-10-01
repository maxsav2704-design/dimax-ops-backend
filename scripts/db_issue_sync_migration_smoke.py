"""Verify issue backfill, rollback and re-upgrade in an empty disposable database."""
import os
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def main() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    if (os.getenv("APP_ENV") != "test" or os.getenv("DIMAX_ISSUE_SYNC_MIGRATION") != "1"
            or url.host != "db" or url.database != "dimax_issue_sync_migrations"):
        raise RuntimeError("Requires the explicitly enabled disposable issue-sync database")
    engine = create_engine(url)
    if inspect(engine).get_table_names():
        raise RuntimeError("Migration check requires an empty disposable database")
    config = Config("alembic.ini")
    previous = "0061_journal_pdf_locale"
    command.upgrade(config, previous)
    from app.modules.identity.infrastructure.models import CompanyORM
    from app.modules.installers.infrastructure.models import InstallerORM
    from app.modules.projects.infrastructure.models import ProjectORM
    from app.modules.door_types.infrastructure.models import DoorTypeORM
    from app.modules.doors.infrastructure.models import DoorORM
    from app.modules.doors.domain.enums import DoorStatus
    from app.modules.issues.infrastructure.models import IssueORM
    from app.modules.issues.domain.enums import IssueStatus

    company_id, project_id, installer_id, type_id = [uuid.uuid4() for _ in range(4)]
    with Session(engine) as session:
        session.add(CompanyORM(id=company_id, name="QA issue migration", is_active=True))
        session.flush()
        session.add_all([
            ProjectORM(id=project_id, company_id=company_id, name="QA issues", address="Test site"),
            InstallerORM(id=installer_id, company_id=company_id, full_name="QA Installer", is_active=True),
            DoorTypeORM(id=type_id, company_id=company_id, code="QA", name="QA door", is_active=True),
        ])
        session.flush()
        for status in (IssueStatus.OPEN, IssueStatus.CLOSED):
            door = DoorORM(
                company_id=company_id, project_id=project_id, door_type_id=type_id,
                installer_id=installer_id, unit_label=status.value, our_price=100,
                status=DoorStatus.NOT_INSTALLED,
            )
            session.add(door)
            session.flush()
            session.add(IssueORM(company_id=company_id, door_id=door.id, status=status, title="Retained issue"))
        session.commit()

    def verify_backfill() -> None:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0062_issue_sync"
            rows = connection.execute(text("SELECT installer_id, payload FROM sync_change_log WHERE change_type='ISSUE'")).all()
            assert len(rows) == 2 and all(row[0] == installer_id for row in rows)
            assert {row[1]["status"] for row in rows} == {"OPEN", "CLOSED"}
            assert all(row[1]["project_id"] == str(project_id) for row in rows)
            assert connection.execute(text("SELECT count(*) FROM completed_work")).scalar_one() == 0

    command.upgrade(config, "head")
    verify_backfill()
    command.downgrade(config, previous)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM issues")).scalar_one() == 2
        assert connection.execute(text("SELECT count(*) FROM sync_change_log WHERE change_type='ISSUE'")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM doors WHERE status='NOT_INSTALLED'")).scalar_one() == 2
    command.upgrade(config, "head")
    verify_backfill()
    engine.dispose()
    print("PASS: empty -> previous -> head -> previous -> head; issue backfill and business rows preserved")


if __name__ == "__main__":
    main()
