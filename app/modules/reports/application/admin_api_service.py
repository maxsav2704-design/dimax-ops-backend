from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.modules.reports.api.schemas import (
    DashboardResponse,
    DeliveryStatsResponse,
    KpiResponse,
    ProblemProjectItem,
    ProblemProjectsResponse,
    ProjectProfitResponse,
    TopReasonItem,
    TopReasonsResponse,
)
from app.modules.reports.application.service import ReportsService
from app.modules.sync.application.health_service import SyncHealthService
from app.shared.domain.errors import NotFound


class ReportsAdminApiService:
    @staticmethod
    def dashboard(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> DashboardResponse:
        kpi_data = ReportsService.kpi(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
        )
        kpi_response = KpiResponse(
            period_from=date_from,
            period_to=date_to,
            **kpi_data,
        )
        sync_health = SyncHealthService.run_for_company(
            uow,
            company_id=company_id,
        )
        return DashboardResponse(kpi=kpi_response, sync_health=sync_health)

    @staticmethod
    def kpi(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> KpiResponse:
        data = ReportsService.kpi(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
        )
        return KpiResponse(
            period_from=date_from,
            period_to=date_to,
            **data,
        )

    @staticmethod
    def problem_projects(
        uow,
        *,
        company_id,
        limit: int,
    ) -> ProblemProjectsResponse:
        items = ReportsService.problem_projects(
            uow.session,
            company_id=company_id,
            limit=limit,
        )
        return ProblemProjectsResponse(items=[ProblemProjectItem(**x) for x in items])

    @staticmethod
    def top_reasons(
        uow,
        *,
        company_id,
        limit: int,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> TopReasonsResponse:
        items = ReportsService.top_reasons(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return TopReasonsResponse(items=[TopReasonItem(**x) for x in items])

    @staticmethod
    def project_profit(
        uow,
        *,
        company_id,
        project_id: UUID,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> ProjectProfitResponse:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found",
                details={"project_id": str(project_id)},
            )

        data = ReportsService.project_profit(
            uow.session,
            company_id=company_id,
            project_id=project_id,
            date_from=date_from,
            date_to=date_to,
        )
        return ProjectProfitResponse(project_id=project_id, **data)

    @staticmethod
    def delivery_stats(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> DeliveryStatsResponse:
        data = ReportsService.delivery_stats(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
        )
        return DeliveryStatsResponse(
            period_from=date_from,
            period_to=date_to,
            **data,
        )
