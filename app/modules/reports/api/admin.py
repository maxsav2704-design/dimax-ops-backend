from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.reports.api.schemas import (
    DashboardResponse,
    DeliveryStatsResponse,
    KpiResponse,
    ProblemProjectsResponse,
    ProjectProfitResponse,
    TopReasonsResponse,
)
from app.modules.reports.application.admin_api_service import ReportsAdminApiService


router = APIRouter(prefix="/admin/reports", tags=["Admin / Reports"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.dashboard(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
        )


@router.get("/kpi", response_model=KpiResponse)
def kpi(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.kpi(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
        )


@router.get("/problem-projects", response_model=ProblemProjectsResponse)
def problem_projects(
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.problem_projects(
            uow,
            company_id=user.company_id,
            limit=limit,
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
        return ReportsAdminApiService.top_reasons(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
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
        return ReportsAdminApiService.project_profit(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            date_from=date_from,
            date_to=date_to,
        )


@router.get("/delivery", response_model=DeliveryStatsResponse)
def delivery_stats(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.delivery_stats(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
        )
