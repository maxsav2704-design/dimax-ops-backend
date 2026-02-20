"""
Sync health worker: periodically runs health check for all companies.
Uses real UoW (context manager) per company; no fake UoW, no blocking API.

Usage: python -m app.scripts.run_sync_health
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone

from app.modules.companies.infrastructure.repositories import CompanyRepository
from app.modules.sync.application.health_service import SyncHealthService
from app.shared.infrastructure.db.session import SessionLocal
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork


INTERVAL_SECONDS = 600  # 10 minutes


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_once() -> None:
    session = SessionLocal()
    try:
        company_repo = CompanyRepository(session)
        companies = company_repo.list_all()
    except Exception:
        traceback.print_exc()
        session.rollback()
        raise
    finally:
        session.close()

    for company in companies:
        try:
            print(
                f"[{_utcnow_iso()}] Running sync health for company {company.id}"
            )
            uow = SqlAlchemyUnitOfWork()
            with uow:
                data = SyncHealthService.run_for_company(
                    uow, company_id=company.id
                )
            print(
                f"[{_utcnow_iso()}] Company {company.id}: "
                f"ok={data['counts']['ok']} warn={data['counts']['warn']} "
                f"danger={data['counts']['danger']} "
                f"alerts_sent={data['alerts_sent']}"
            )
        except Exception:
            traceback.print_exc()


def main() -> None:
    print("Sync health worker started")
    while True:
        try:
            run_once()
        except Exception:
            traceback.print_exc()
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
