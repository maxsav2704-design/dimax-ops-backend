from __future__ import annotations

from uuid import UUID

from app.modules.sync.application.health_service import SyncHealthService


class AdminSyncHealthApiService:
    @staticmethod
    def run_health_check(uow, *, company_id: UUID) -> dict:
        data = SyncHealthService.run_for_company(uow, company_id=company_id)
        return {"ok": True, "data": data}

    @staticmethod
    def get_health_summary(uow, *, company_id: UUID) -> dict:
        return SyncHealthService.run_for_company(uow, company_id=company_id)
