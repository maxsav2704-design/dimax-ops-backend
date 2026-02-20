"""
Sync health worker: runs SyncHealthService.run_for_company for all companies
every SYNC_HEALTH_INTERVAL_SECONDS. No FastAPI/uvicorn dependency.

Usage: python -m app.scripts.run_sync_health_job
"""
from __future__ import annotations

import os
import time
import traceback
from datetime import datetime, timezone

from app.modules.sync.application.health_service import SyncHealthService
from app.shared.infrastructure.db.session import SessionLocal
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork


INTERVAL_SECONDS = int(os.getenv("SYNC_HEALTH_INTERVAL_SECONDS", "600"))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_once() -> None:
    # Get company IDs via one UoW (each UoW creates its own session)
    with SqlAlchemyUnitOfWork() as uow:
        company_ids = uow.companies.list_ids()

    for cid in company_ids:
        try:
            with SqlAlchemyUnitOfWork() as uow:
                SyncHealthService.run_for_company(uow, company_id=cid)
            print(f"[{utcnow()}] sync_health OK company={cid}")
        except Exception:
            print(f"[{utcnow()}] sync_health FAIL company={cid}")
            traceback.print_exc()


def main() -> None:
    print(f"[{utcnow()}] sync_health job started interval={INTERVAL_SECONDS}s")
    while True:
        try:
            run_once()
        except Exception:
            print(f"[{utcnow()}] sync_health loop FAIL")
            traceback.print_exc()
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
