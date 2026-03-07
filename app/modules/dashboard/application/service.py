from __future__ import annotations

from app.modules.companies.application.metrics_service import CompanyMetricsService
from app.modules.dashboard.infrastructure.repositories import DashboardRepository
from app.modules.sync.application.health_service import SyncHealthService


class DashboardService:
    @staticmethod
    def get_dashboard(uow, *, company_id, actor_user_id) -> dict:
        sync_health = SyncHealthService.run_for_company(uow, company_id=company_id)
        limits = CompanyMetricsService.limits_kpi(uow, company_id=company_id)
        audit_repo = getattr(uow, "audit", None)
        unread_count = 0
        if audit_repo is not None:
            cursor = audit_repo.get_alert_read_cursor(
                company_id=company_id,
                user_id=actor_user_id,
            )
            unread_count = audit_repo.count_limit_alerts_since(
                company_id=company_id,
                since=cursor.last_read_at if cursor else None,
            )
        return DashboardRepository.compose_dashboard(
            sync_health=sync_health,
            limits=limits,
            limit_alerts_unread_count=unread_count,
        )
