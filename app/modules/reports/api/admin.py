from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.reports.api.schemas import (
    AuditCatalogChangesResponse,
    DashboardResponse,
    DeliveryStatsResponse,
    DispatcherBoardResponse,
    InstallerKpiDetailsResponse,
    InstallerProjectProfitabilityResponse,
    InstallerProfitabilityMatrixResponse,
    InstallersKpiResponse,
    IssuesAddonsImpactResponse,
    IssuesAnalyticsResponse,
    KpiResponse,
    LimitAlertsReadRequest,
    LimitAlertsReadResponse,
    LimitAlertsResponse,
    LimitsKpiResponse,
    OrderNumbersKpiResponse,
    OperationsCenterResponse,
    OperationsSlaHistoryResponse,
    OperationsSlaResponse,
    ProblemProjectsResponse,
    ProjectsMarginResponse,
    ProjectPlanFactResponse,
    ProjectRiskDrilldownResponse,
    ProjectProfitResponse,
    RiskConcentrationResponse,
    TopReasonsResponse,
)
from app.modules.reports.application.admin_api_service import ReportsAdminApiService


router = APIRouter(prefix="/admin/reports", tags=["Admin / Reports"])
InstallersKpiSortBy = Literal[
    "installed_doors",
    "payroll_total",
    "revenue_total",
    "profit_total",
    "installer_name",
]
OrderNumbersKpiSortBy = Literal[
    "order_number",
    "total_doors",
    "installed_doors",
    "not_installed_doors",
    "planned_revenue_total",
    "installed_revenue_total",
    "payroll_total",
    "profit_total",
    "missing_rates_installed_doors",
]
ProjectsMarginSortBy = Literal[
    "profit_total",
    "margin_pct",
    "completion_pct",
    "open_issues",
]
InstallerProfitabilityMatrixSortBy = Literal[
    "profit_total",
    "margin_pct",
    "installed_doors",
    "avg_profit_per_door",
    "open_issues",
]
InstallerProjectProfitabilitySortBy = Literal[
    "profit_total",
    "margin_pct",
    "installed_doors",
    "open_issues",
    "avg_profit_per_door",
]
SortDir = Literal["asc", "desc"]


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


@router.get("/limits", response_model=LimitsKpiResponse)
def limits(
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.limits(
            uow,
            company_id=user.company_id,
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


@router.get("/dispatcher-board", response_model=DispatcherBoardResponse)
def dispatcher_board(
    projects_limit: int = Query(default=8, ge=1, le=25),
    installers_limit: int = Query(default=8, ge=1, le=25),
    recommendation_limit: int = Query(default=3, ge=1, le=10),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.dispatcher_board(
            uow,
            company_id=user.company_id,
            now=datetime.now(timezone.utc),
            projects_limit=projects_limit,
            installers_limit=installers_limit,
            recommendation_limit=recommendation_limit,
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


@router.get("/installers-kpi", response_model=InstallersKpiResponse)
def installers_kpi(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    sort_by: InstallersKpiSortBy = Query(default="installed_doors"),
    sort_dir: SortDir = Query(default="desc"),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.installers_kpi(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )


@router.get(
    "/installers-profitability-matrix",
    response_model=InstallerProfitabilityMatrixResponse,
)
def installer_profitability_matrix(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: InstallerProfitabilityMatrixSortBy = Query(default="profit_total"),
    sort_dir: SortDir = Query(default="desc"),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.installer_profitability_matrix(
            uow,
            company_id=user.company_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )


@router.get(
    "/installer-project-profitability",
    response_model=InstallerProjectProfitabilityResponse,
)
def installer_project_profitability(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: InstallerProjectProfitabilitySortBy = Query(default="profit_total"),
    sort_dir: SortDir = Query(default="desc"),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.installer_project_profitability(
            uow,
            company_id=user.company_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )


@router.get(
    "/installers-kpi/export",
    response_class=Response,
    responses={
        200: {
            "description": "CSV export",
            "content": {
                "text/csv": {
                    "schema": {"type": "string"}
                }
            },
        }
    },
)
def installers_kpi_export(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    sort_by: InstallersKpiSortBy = Query(default="installed_doors"),
    sort_dir: SortDir = Query(default="desc"),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        content = ReportsAdminApiService.installers_kpi_export_csv(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"installers_kpi_{ts}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/installers-kpi/{installer_id}", response_model=InstallerKpiDetailsResponse)
def installer_kpi_details(
    installer_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.installer_kpi_details(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
        )


@router.get("/order-numbers-kpi", response_model=OrderNumbersKpiResponse)
def order_numbers_kpi(
    project_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    sort_by: OrderNumbersKpiSortBy = Query(default="total_doors"),
    sort_dir: SortDir = Query(default="desc"),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.order_numbers_kpi(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            q=q,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )


@router.get(
    "/order-numbers-kpi/export",
    response_class=Response,
    responses={
        200: {
            "description": "CSV export",
            "content": {
                "text/csv": {
                    "schema": {"type": "string"}
                }
            },
        }
    },
)
def order_numbers_kpi_export(
    project_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    sort_by: OrderNumbersKpiSortBy = Query(default="total_doors"),
    sort_dir: SortDir = Query(default="desc"),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        content = ReportsAdminApiService.order_numbers_kpi_export_csv(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            q=q,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"order_numbers_kpi_{ts}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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


@router.get("/project-plan-fact/{project_id}", response_model=ProjectPlanFactResponse)
def project_plan_fact(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.project_plan_fact(
            uow,
            company_id=user.company_id,
            project_id=project_id,
        )


@router.get(
    "/project-risk-drilldown/{project_id}",
    response_model=ProjectRiskDrilldownResponse,
)
def project_risk_drilldown(
    project_id: UUID,
    limit: int = Query(default=5, ge=1, le=20),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.project_risk_drilldown(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            limit=limit,
        )


@router.get("/projects-margin", response_model=ProjectsMarginResponse)
def projects_margin(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: ProjectsMarginSortBy = Query(default="profit_total"),
    sort_dir: SortDir = Query(default="desc"),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.projects_margin(
            uow,
            company_id=user.company_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )


@router.get("/issues-addons-impact", response_model=IssuesAddonsImpactResponse)
def issues_addons_impact(
    limit: int = Query(default=10, ge=1, le=50),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.issues_addons_impact(
            uow,
            company_id=user.company_id,
            limit=limit,
        )


@router.get("/risk-concentration", response_model=RiskConcentrationResponse)
def risk_concentration(
    limit: int = Query(default=5, ge=1, le=20),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.risk_concentration(
            uow,
            company_id=user.company_id,
            limit=limit,
        )


@router.get(
    "/executive/export",
    response_class=Response,
    responses={
        200: {
            "description": "CSV export",
            "content": {
                "text/csv": {
                    "schema": {"type": "string"}
                }
            },
        }
    },
)
def executive_export(
    project_plan_fact_project_id: UUID | None = Query(default=None),
    project_risk_project_id: UUID | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        content, filename = ReportsAdminApiService.executive_export_csv(
            uow,
            company_id=user.company_id,
            project_plan_fact_project_id=project_plan_fact_project_id,
            project_risk_project_id=project_risk_project_id,
        )
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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


@router.get("/audit-catalogs", response_model=AuditCatalogChangesResponse)
def audit_catalog_changes(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.audit_catalog_changes(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
            entity_type=entity_type,
            action=action,
            limit=limit,
            offset=offset,
        )


@router.get("/audit-issues", response_model=AuditCatalogChangesResponse)
def audit_issue_changes(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    action: str | None = Query(default=None),
    issue_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.audit_issue_changes(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            issue_id=issue_id,
            limit=limit,
            offset=offset,
        )


@router.get("/audit-installer-rates", response_model=AuditCatalogChangesResponse)
def audit_installer_rate_changes(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    action: str | None = Query(default=None),
    rate_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.audit_installer_rate_changes(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            rate_id=rate_id,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/audit-catalogs/export",
    response_class=Response,
    responses={
        200: {
            "description": "CSV export",
            "content": {
                "text/csv": {
                    "schema": {"type": "string"}
                }
            },
        }
    },
)
def audit_catalog_changes_export(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        content = ReportsAdminApiService.audit_catalog_changes_export_csv(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
            entity_type=entity_type,
            action=action,
            limit=limit,
        )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"audit_catalogs_{ts}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/audit-issues/export",
    response_class=Response,
    responses={
        200: {
            "description": "CSV export",
            "content": {
                "text/csv": {
                    "schema": {"type": "string"}
                }
            },
        }
    },
)
def audit_issue_changes_export(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    action: str | None = Query(default=None),
    issue_id: UUID | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        content = ReportsAdminApiService.audit_issue_changes_export_csv(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            issue_id=issue_id,
            limit=limit,
        )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"audit_issues_{ts}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/audit-installer-rates/export",
    response_class=Response,
    responses={
        200: {
            "description": "CSV export",
            "content": {
                "text/csv": {
                    "schema": {"type": "string"}
                }
            },
        }
    },
)
def audit_installer_rate_changes_export(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    action: str | None = Query(default=None),
    rate_id: UUID | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        content = ReportsAdminApiService.audit_installer_rate_changes_export_csv(
            uow,
            company_id=user.company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            rate_id=rate_id,
            limit=limit,
        )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"audit_installer_rates_{ts}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/limit-alerts", response_model=LimitAlertsResponse)
def limit_alerts(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.limit_alerts(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            limit=limit,
            offset=offset,
        )


@router.post("/limit-alerts/read", response_model=LimitAlertsReadResponse)
def mark_limit_alerts_read(
    body: LimitAlertsReadRequest,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.mark_limit_alerts_read(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            read_up_to=body.read_up_to,
        )


@router.get("/operations-center", response_model=OperationsCenterResponse)
def operations_center(
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.operations_center(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
        )


@router.get("/operations-sla", response_model=OperationsSlaResponse)
def operations_sla(
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.operations_sla(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
        )


@router.get("/operations-sla/history", response_model=OperationsSlaHistoryResponse)
def operations_sla_history(
    days: int = Query(default=30, ge=7, le=90),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.operations_sla_history(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            days=days,
        )


@router.get("/issues-analytics", response_model=IssuesAnalyticsResponse)
def issues_analytics(
    days: int = Query(default=30, ge=7, le=90),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ReportsAdminApiService.issues_analytics(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            days=days,
        )
