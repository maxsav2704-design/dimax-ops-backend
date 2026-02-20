from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
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


router = APIRouter(prefix="/admin/reports", tags=["Admin / Reports"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        kpi_data = ReportsService.kpi(
            uow.session,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
        )
        kpi_response = KpiResponse(
            period_from=date_from,
            period_to=date_to,
            **kpi_data,
        )
        sync_health = SyncHealthService.run_for_company(
            uow, company_id=user.company_id
        )
        return DashboardResponse(kpi=kpi_response, sync_health=sync_health)


@router.get("/kpi", response_model=KpiResponse)
def kpi(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        data = ReportsService.kpi(
            uow.session,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
        )
        return KpiResponse(
            period_from=date_from,
            period_to=date_to,
            **data,
        )


@router.get("/problem-projects", response_model=ProblemProjectsResponse)
def problem_projects(
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        items = ReportsService.problem_projects(
            uow.session,
            company_id=user.company_id,
            limit=limit,
        )
        return ProblemProjectsResponse(
            items=[ProblemProjectItem(**x) for x in items]
        )


@router.get("/top-reasons", response_model=TopReasonsResponse)
def top_reasons(
    limit: int = Query(default=10, ge=1, le=50),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        items = ReportsService.top_reasons(
            uow.session,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return TopReasonsResponse(
            items=[TopReasonItem(**x) for x in items]
        )


@router.get("/project-profit/{project_id}", response_model=ProjectProfitResponse)
def project_profit(
    project_id: UUID,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        p = uow.projects.get(
            company_id=user.company_id, project_id=project_id
        )
        if not p:
            raise NotFound(
                "Project not found", details={"project_id": str(project_id)}
            )

        data = ReportsService.project_profit(
            uow.session,
            company_id=user.company_id,
            project_id=project_id,
            date_from=date_from,
            date_to=date_to,
        )
        return ProjectProfitResponse(project_id=project_id, **data)


@router.get("/delivery", response_model=DeliveryStatsResponse)
def delivery_stats(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        data = ReportsService.delivery_stats(
            uow.session,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
        )
        return DeliveryStatsResponse(
            period_from=date_from,
            period_to=date_to,
            **data,
        )
