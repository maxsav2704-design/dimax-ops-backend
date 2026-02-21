from __future__ import annotations

from app.modules.dashboard.infrastructure.repositories import DashboardRepository
from app.modules.sync.application.health_service import SyncHealthService


class DashboardService:
    @staticmethod
    def get_dashboard(uow, *, company_id) -> dict:
        sync_health = SyncHealthService.run_for_company(uow, company_id=company_id)
        return DashboardRepository.compose_dashboard(sync_health=sync_health)
