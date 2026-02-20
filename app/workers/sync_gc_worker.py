from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.sync.infrastructure.models import SyncChangeLogORM
from app.modules.sync.infrastructure.repositories import (
    InstallerSyncStateRepository,
    SyncChangeLogGCRepository,
)
from app.shared.infrastructure.db.session import SessionLocal


def run_once() -> None:
    session: Session = SessionLocal()
    try:
        state_repo = InstallerSyncStateRepository(session)
        gc_repo = SyncChangeLogGCRepository(session)

        company_ids = [
            row[0]
            for row in session.query(SyncChangeLogORM.company_id)
            .distinct()
            .all()
        ]

        total_deleted = 0
        for company_id in company_ids:
            installers = state_repo.active_installers_count(
                company_id=company_id
            )
            if installers <= 0:
                continue

            min_ack = state_repo.min_ack_for_company(
                company_id=company_id,
                active_days=settings.SYNC_ACTIVE_DAYS,
            )
            cutoff = int(min_ack) - int(settings.SYNC_GC_SAFETY_LAG)
            if cutoff <= 0:
                continue

            deleted = gc_repo.delete_upto_cursor(
                company_id=company_id, max_cursor_inclusive=cutoff
            )
            total_deleted += deleted

        session.commit()
        if total_deleted:
            print(
                f"🧹 sync_change_log GC deleted={total_deleted} at "
                f"{datetime.utcnow().isoformat()}Z"
            )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    while True:
        run_once()
        time.sleep(3600)


if __name__ == "__main__":
    main()
