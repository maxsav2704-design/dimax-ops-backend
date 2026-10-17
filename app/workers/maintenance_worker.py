from __future__ import annotations

import time

from sqlalchemy import select

from app.modules.files.infrastructure.repositories import FileTokenRepository
from app.modules.sync.application.health_service import SyncHealthService
from app.modules.sync.infrastructure.models import InstallerSyncStateORM
from app.shared.infrastructure.db.session import SessionLocal
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork


def cleanup_file_tokens() -> int:
    session = SessionLocal()
    try:
        repo = FileTokenRepository(session)
        deleted = repo.delete_expired_and_used()
        session.commit()
        return deleted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_sync_health() -> int:
    """Evaluate installer sync health for every company that has sync state.

    This is the only periodic writer: it stores the health columns, sends the
    danger webhook and opens / closes the sync-risk issues. The dashboards read
    the stored result without side effects.
    """
    session = SessionLocal()
    try:
        company_ids = list(session.scalars(select(InstallerSyncStateORM.company_id).distinct()))
    finally:
        session.close()
    evaluated = 0
    for company_id in company_ids:
        uow = SqlAlchemyUnitOfWork()
        try:
            with uow:
                SyncHealthService.run_for_company(uow, company_id=company_id)
                uow.commit()
            evaluated += 1
        except Exception as exc:  # one company must not stop the others
            print(f"sync health failed for company {company_id}: {type(exc).__name__}")
    return evaluated


def main() -> None:
    while True:
        deleted = cleanup_file_tokens()
        if deleted:
            print(f"🧹 file tokens cleaned: {deleted}")
        evaluated = run_sync_health()
        if evaluated:
            print(f"🩺 sync health evaluated for {evaluated} companies")
        time.sleep(600)


if __name__ == "__main__":
    main()
