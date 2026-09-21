"""Exercise the full migration chain and one-step rollback in an empty QA database."""
import os
import uuid
from datetime import datetime, timezone

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def main():
    url = make_url(os.environ["DATABASE_URL"])
    if (os.getenv("APP_ENV") != "test" or os.getenv("DIMAX_JOURNAL_LOCALE_MIGRATION") != "1"
            or url.host != "db" or url.database != "dimax_journal_locale_migrations"):
        raise RuntimeError("Requires the explicitly enabled, isolated locale migration database")
    engine = create_engine(url)
    if inspect(engine).get_table_names():
        raise RuntimeError("Migration check requires an empty disposable database")
    config = Config("alembic.ini")
    previous = "0060_installer_journal_handoff"
    command.upgrade(config, previous)
    from app.modules.identity.infrastructure.models import CompanyORM
    from app.modules.projects.infrastructure.models import ProjectORM
    from app.modules.projects.domain.enums import ProjectStatus
    from app.modules.journal.infrastructure.models import JournalFileORM

    cid, pid, jid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(CompanyORM(id=cid, name="QA locale migration", is_active=True))
        session.flush()
        session.add(ProjectORM(
            id=pid, company_id=cid, name="QA legacy journal",
            address="QA migration address", status=ProjectStatus.OK,
        ))
        session.flush()
        legacy = Table("journals", MetaData(), autoload_with=engine)
        session.execute(legacy.insert().values(
            id=jid, company_id=cid, project_id=pid, status="ARCHIVED", title="QA legacy archive",
            lock_header=True, lock_table=True, lock_footer=True, snapshot_version=1,
            signed_at=now, signer_name="QA Signer", email_delivery_status="NONE",
            whatsapp_delivery_status="NONE", created_at=now, updated_at=now,
        ))
        session.add(JournalFileORM(
            company_id=cid, journal_id=jid, kind="PDF", file_path="qa-legacy-signed.pdf",
            mime_type="application/pdf", size_bytes=123, storage_provider="MINIO", bucket="qa",
        ))
        session.commit()
    command.upgrade(config, "head")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT pdf_locale FROM journals WHERE id=:id"), {"id": jid}).scalar_one() == "en"
        assert connection.execute(text("SELECT file_path FROM journal_files WHERE journal_id=:id"), {"id": jid}).scalar_one() == "qa-legacy-signed.pdf"
        connection.execute(text("UPDATE journals SET pdf_locale='he' WHERE id=:id"), {"id": jid})
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE journals SET pdf_locale='zz' WHERE id=:id"), {"id": jid})
    except IntegrityError as error:
        assert "ck_journals_pdf_locale" in str(error)
    else:
        raise AssertionError("Database accepted an invalid PDF language")
    command.downgrade(config, previous)
    assert "pdf_locale" not in {column["name"] for column in inspect(engine).get_columns("journals")}
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0061_journal_pdf_locale"
        assert connection.execute(text("SELECT pdf_locale FROM journals WHERE id=:id"), {"id": jid}).scalar_one() == "en"
    engine.dispose()
    print("PASS: empty database -> legacy -> head -> legacy -> head; default, constraint and archive reference preserved")


if __name__ == "__main__":
    main()
