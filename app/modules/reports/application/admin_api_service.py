from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import UUID

from app.modules.reports.api.schemas import (
    AuditCatalogChangeItem,
    AuditCatalogChangesResponse,
    AuditCatalogChangesSummary,
    DashboardResponse,
    DeliveryStatsResponse,
    DispatcherBoardResponse,
    DispatcherBoardSummaryResponse,
    DispatcherInstallerItem,
    InstallerKpiDetailsResponse,
    InstallerKpiItem,
    InstallerKpiOrderItem,
    InstallerProjectProfitabilityItem,
    InstallerProjectProfitabilityResponse,
    InstallerKpiProjectItem,
    InstallerProfitabilityMatrixItem,
    InstallerProfitabilityMatrixResponse,
    InstallersKpiResponse,
    IssuesAddonsImpactAddonItem,
    IssuesAddonsImpactReasonItem,
    IssuesAddonsImpactResponse,
    IssuesAddonsImpactSummaryResponse,
    IssuesAnalyticsResponse,
    IssuesAnalyticsSummaryResponse,
    IssuesAnalyticsTrendPointResponse,
    KpiResponse,
    LimitAlertItem,
    LimitAlertsReadResponse,
    LimitAlertsResponse,
    LimitsKpiResponse,
    OrderNumberKpiItem,
    OrderNumbersKpiResponse,
    OperationsCenterAlertsSummary,
    OperationsCenterFailingProjectItem,
    OperationsCenterImportsSummary,
    OperationsCenterOutboxSummary,
    OperationsCenterResponse,
    OperationsSlaHistoryPointResponse,
    OperationsSlaHistoryResponse,
    OperationsSlaHistorySummaryResponse,
    OperationsSlaMetricResponse,
    OperationsSlaPlaybookResponse,
    OperationsSlaResponse,
    ProblemProjectItem,
    ProblemProjectsResponse,
    DispatcherProjectInstallerRecommendationItem,
    DispatcherProjectItem,
    ProjectMarginItem,
    RiskConcentrationResponse,
    RiskConcentrationSummaryResponse,
    ProjectRiskDrilldownResponse,
    ProjectRiskDrilldownSummaryResponse,
    ProjectRiskDriverItem,
    ProjectRiskOrderItem,
    ProjectRiskReasonItem,
    ProjectsMarginResponse,
    ProjectPlanFactResponse,
    ProjectProfitResponse,
    TopReasonItem,
    TopReasonsResponse,
)
from app.modules.companies.application.metrics_service import CompanyMetricsService
from app.modules.reports.application.service import ReportsService
from app.modules.sync.application.health_service import SyncHealthService
from app.shared.domain.errors import NotFound, ValidationError


class ReportsAdminApiService:
    ALLOWED_AUDIT_CATALOG_ENTITIES = {
        "door_type",
        "reason",
        "company",
        "project",
        "installer_rate",
    }
    ALLOWED_AUDIT_CATALOG_ACTIONS = {
        "DOOR_TYPE_CREATE",
        "DOOR_TYPE_UPDATE",
        "DOOR_TYPE_DELETE",
        "REASON_CREATE",
        "REASON_UPDATE",
        "REASON_DELETE",
        "SETTINGS_COMPANY_UPDATE",
        "PROJECT_DOORS_IMPORT_ANALYZE",
        "PROJECT_DOORS_IMPORT_APPLY",
        "PROJECT_DOORS_IMPORT_RETRY",
        "PROJECT_DOORS_IMPORT_RETRY_BULK",
        "INSTALLER_RATE_CREATE",
        "INSTALLER_RATE_UPDATE",
        "INSTALLER_RATE_DELETE",
    }
    ALLOWED_AUDIT_ISSUE_ACTIONS = {
        "ISSUE_STATUS_UPDATE",
        "ISSUE_WORKFLOW_UPDATE",
        "ISSUE_WORKFLOW_BULK_UPDATE",
    }
    ALLOWED_AUDIT_INSTALLER_RATE_ACTIONS = {
        "INSTALLER_RATE_CREATE",
        "INSTALLER_RATE_UPDATE",
        "INSTALLER_RATE_DELETE",
    }

    @staticmethod
    def _metric_status(*, value: float, warn: float, danger: float) -> str:
        if value >= danger:
            return "DANGER"
        if value >= warn:
            return "WARN"
        return "OK"

    @staticmethod
    def _overall_status(statuses: list[str]) -> str:
        if any(x == "DANGER" for x in statuses):
            return "DANGER"
        if any(x == "WARN" for x in statuses):
            return "WARN"
        return "OK"

    @staticmethod
    def _validate_audit_catalog_filters(
        *,
        entity_type: str | None,
        action: str | None,
    ) -> None:
        if (
            entity_type is not None
            and entity_type not in ReportsAdminApiService.ALLOWED_AUDIT_CATALOG_ENTITIES
        ):
            raise ValidationError("unsupported entity_type")
        if (
            action is not None
            and action not in ReportsAdminApiService.ALLOWED_AUDIT_CATALOG_ACTIONS
        ):
            raise ValidationError("unsupported action")

    @staticmethod
    def _validate_audit_issue_filters(
        *,
        action: str | None,
    ) -> None:
        if (
            action is not None
            and action not in ReportsAdminApiService.ALLOWED_AUDIT_ISSUE_ACTIONS
        ):
            raise ValidationError("unsupported action")

    @staticmethod
    def _validate_audit_installer_rate_filters(
        *,
        action: str | None,
    ) -> None:
        if (
            action is not None
            and action not in ReportsAdminApiService.ALLOWED_AUDIT_INSTALLER_RATE_ACTIONS
        ):
            raise ValidationError("unsupported action")

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
        limits_data = CompanyMetricsService.limits_kpi(uow, company_id=company_id)
        limits_response = LimitsKpiResponse(**limits_data)
        return DashboardResponse(
            kpi=kpi_response,
            sync_health=sync_health,
            limits=limits_response,
        )

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
    def limits(
        uow,
        *,
        company_id,
    ) -> LimitsKpiResponse:
        limits_data = CompanyMetricsService.limits_kpi(uow, company_id=company_id)
        return LimitsKpiResponse(**limits_data)

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
    def dispatcher_board(
        uow,
        *,
        company_id,
        now: datetime,
        projects_limit: int,
        installers_limit: int,
        recommendation_limit: int,
    ) -> DispatcherBoardResponse:
        data = ReportsService.dispatcher_board(
            uow.session,
            company_id=company_id,
            now=now,
            projects_limit=projects_limit,
            installers_limit=installers_limit,
            recommendation_limit=recommendation_limit,
        )
        return DispatcherBoardResponse(
            generated_at=now,
            summary=DispatcherBoardSummaryResponse(**dict(data.get("summary", {}))),
            projects=[
                DispatcherProjectItem(
                    **{
                        **item,
                        "recommended_installers": [
                            DispatcherProjectInstallerRecommendationItem(**rec)
                            for rec in item.get("recommended_installers", [])
                        ],
                    }
                )
                for item in data.get("projects", [])
            ],
            installers=[
                DispatcherInstallerItem(**item) for item in data.get("installers", [])
            ],
        )

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
    def installers_kpi(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
        sort_by: str,
        sort_dir: str,
    ) -> InstallersKpiResponse:
        items = ReportsService.installers_kpi(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        return InstallersKpiResponse(
            period_from=date_from,
            period_to=date_to,
            items=[InstallerKpiItem(**x) for x in items],
        )

    @staticmethod
    def installer_profitability_matrix(
        uow,
        *,
        company_id,
        limit: int,
        offset: int,
        sort_by: str,
        sort_dir: str,
    ) -> InstallerProfitabilityMatrixResponse:
        data = ReportsService.installer_profitability_matrix(
            uow.session,
            company_id=company_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        return InstallerProfitabilityMatrixResponse(
            total=int(data.get("total", 0)),
            limit=limit,
            offset=offset,
            items=[
                InstallerProfitabilityMatrixItem(**item)
                for item in data.get("items", [])
            ],
        )

    @staticmethod
    def installer_project_profitability(
        uow,
        *,
        company_id,
        limit: int,
        offset: int,
        sort_by: str,
        sort_dir: str,
    ) -> InstallerProjectProfitabilityResponse:
        data = ReportsService.installer_project_profitability(
            uow.session,
            company_id=company_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        return InstallerProjectProfitabilityResponse(
            total=int(data.get("total", 0)),
            limit=limit,
            offset=offset,
            items=[
                InstallerProjectProfitabilityItem(**item)
                for item in data.get("items", [])
            ],
        )

    @staticmethod
    def risk_concentration(
        uow,
        *,
        company_id,
        limit: int,
    ) -> RiskConcentrationResponse:
        data = ReportsService.risk_concentration(
            uow.session,
            company_id=company_id,
            limit=limit,
        )
        return RiskConcentrationResponse(
            generated_at=datetime.now(timezone.utc),
            summary=RiskConcentrationSummaryResponse(**dict(data.get("summary", {}))),
            projects=[ProjectMarginItem(**item) for item in data.get("projects", [])],
            orders=[OrderNumberKpiItem(**item) for item in data.get("orders", [])],
            installers=[
                InstallerProfitabilityMatrixItem(**item)
                for item in data.get("installers", [])
            ],
        )

    @staticmethod
    def installer_kpi_details(
        uow,
        *,
        company_id,
        installer_id: UUID,
    ) -> InstallerKpiDetailsResponse:
        installer = uow.installers.get(company_id, installer_id)
        if not installer:
            raise NotFound(
                "Installer not found",
                details={"installer_id": str(installer_id)},
            )

        data = ReportsService.installer_kpi_details(
            uow.session,
            company_id=company_id,
            installer_id=installer_id,
        )
        return InstallerKpiDetailsResponse(
            installer_id=installer_id,
            installer_name=installer.full_name,
            installed_doors=int(data.get("installed_doors", 0)),
            active_projects=int(data.get("active_projects", 0)),
            order_numbers=int(data.get("order_numbers", 0)),
            open_issues=int(data.get("open_issues", 0)),
            addons_done_qty=data.get("addons_done_qty", 0),
            addon_revenue_total=data.get("addon_revenue_total", 0),
            addon_payroll_total=data.get("addon_payroll_total", 0),
            addon_profit_total=data.get("addon_profit_total", 0),
            revenue_total=data.get("revenue_total", 0),
            payroll_total=data.get("payroll_total", 0),
            profit_total=data.get("profit_total", 0),
            missing_rates_installed_doors=int(
                data.get("missing_rates_installed_doors", 0)
            ),
            missing_addon_plans_facts=int(data.get("missing_addon_plans_facts", 0)),
            last_installed_at=data.get("last_installed_at"),
            top_projects=[
                InstallerKpiProjectItem(**item)
                for item in data.get("top_projects", [])
            ],
            order_breakdown=[
                InstallerKpiOrderItem(**item)
                for item in data.get("order_breakdown", [])
            ],
        )

    @staticmethod
    def executive_export_csv(
        uow,
        *,
        company_id,
        project_plan_fact_project_id: UUID | None,
        project_risk_project_id: UUID | None,
    ) -> tuple[str, str]:
        project_plan_fact = None
        project_plan_fact_name = None
        if project_plan_fact_project_id is not None:
            project = uow.projects.get(
                company_id=company_id,
                project_id=project_plan_fact_project_id,
            )
            if not project:
                raise NotFound(
                    "Project not found",
                    details={"project_id": str(project_plan_fact_project_id)},
                )
            project_plan_fact_name = project.name
            project_plan_fact = ReportsService.project_plan_fact(
                uow.session,
                company_id=company_id,
                project_id=project_plan_fact_project_id,
            )

        project_risk = None
        project_risk_name = None
        if project_risk_project_id is not None:
            project = uow.projects.get(
                company_id=company_id,
                project_id=project_risk_project_id,
            )
            if not project:
                raise NotFound(
                    "Project not found",
                    details={"project_id": str(project_risk_project_id)},
                )
            project_risk_name = project.name
            project_risk = ReportsService.project_risk_drilldown(
                uow.session,
                company_id=company_id,
                project_id=project_risk_project_id,
                limit=5,
            )

        risk_concentration = ReportsService.risk_concentration(
            uow.session,
            company_id=company_id,
            limit=5,
        )
        issues_addons_impact = ReportsService.issues_addons_impact(
            uow.session,
            company_id=company_id,
            limit=5,
        )
        top_projects = ReportsService.projects_margin(
            uow.session,
            company_id=company_id,
            limit=5,
            offset=0,
            sort_by="profit_total",
            sort_dir="desc",
        )
        risk_projects = ReportsService.projects_margin(
            uow.session,
            company_id=company_id,
            limit=5,
            offset=0,
            sort_by="profit_total",
            sort_dir="asc",
        )
        installers_matrix = ReportsService.installer_profitability_matrix(
            uow.session,
            company_id=company_id,
            limit=8,
            offset=0,
            sort_by="profit_total",
            sort_dir="desc",
        )
        installer_project = ReportsService.installer_project_profitability(
            uow.session,
            company_id=company_id,
            limit=10,
            offset=0,
            sort_by="profit_total",
            sort_dir="desc",
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["section", "metric", "value_1", "value_2", "value_3", "value_4"])
        writer.writerow(
            [
                "meta",
                "generated_at",
                datetime.now(timezone.utc).isoformat(),
                "",
                "",
                "",
            ]
        )

        summary = dict(risk_concentration.get("summary", {}))
        writer.writerow(
            [
                "executive_summary",
                "risk_concentration",
                summary.get("open_issue_profit_at_risk", 0),
                summary.get("blocked_issue_profit_at_risk", 0),
                summary.get("delayed_profit_total", 0),
                "",
            ]
        )
        writer.writerow(
            [
                "executive_summary",
                "risk_entities",
                summary.get("risky_projects", 0),
                summary.get("risky_orders", 0),
                summary.get("risky_installers", 0),
                "",
            ]
        )

        leakage_summary = dict(issues_addons_impact.get("summary", {}))
        writer.writerow(
            [
                "margin_leakage",
                "issue_and_delay_profit",
                leakage_summary.get("open_issue_profit_at_risk", 0),
                leakage_summary.get("blocked_issue_profit_at_risk", 0),
                leakage_summary.get("delayed_profit_total", 0),
                leakage_summary.get("addon_profit_total", 0),
            ]
        )

        for item in top_projects.get("items", []):
            writer.writerow(
                [
                    "top_projects",
                    item.get("project_name", ""),
                    item.get("profit_total", 0),
                    item.get("margin_pct", 0),
                    item.get("completion_pct", 0),
                    item.get("open_issues", 0),
                ]
            )

        for item in risk_projects.get("items", []):
            writer.writerow(
                [
                    "risk_projects",
                    item.get("project_name", ""),
                    item.get("profit_total", 0),
                    item.get("margin_pct", 0),
                    item.get("completion_pct", 0),
                    item.get("open_issues", 0),
                ]
            )

        for item in installers_matrix.get("items", []):
            writer.writerow(
                [
                    "installers_matrix",
                    item.get("installer_name", ""),
                    item.get("performance_band", ""),
                    item.get("profit_total", 0),
                    item.get("margin_pct", 0),
                    item.get("open_issues", 0),
                ]
            )

        for item in installer_project.get("items", []):
            writer.writerow(
                [
                    "installer_project_cross_view",
                    item.get("installer_name", ""),
                    item.get("project_name", ""),
                    item.get("profit_total", 0),
                    item.get("margin_pct", 0),
                    item.get("open_issues", 0),
                ]
            )

        if project_plan_fact is not None:
            writer.writerow(
                [
                    "project_plan_fact",
                    project_plan_fact_name or "",
                    project_plan_fact.get("planned_profit_total", 0),
                    project_plan_fact.get("actual_profit_total", 0),
                    project_plan_fact.get("profit_gap_total", 0),
                    project_plan_fact.get("completion_pct", 0),
                ]
            )

        if project_risk is not None:
            risk_summary = dict(project_risk.get("summary", {}))
            writer.writerow(
                [
                    "project_risk_drilldown",
                    project_risk_name or "",
                    risk_summary.get("profit_gap_total", 0),
                    risk_summary.get("delayed_profit_total", 0),
                    risk_summary.get("blocked_issue_profit_at_risk", 0),
                    risk_summary.get("actual_margin_pct", 0),
                ]
            )

        filename = "reports_executive_snapshot.csv"
        if project_plan_fact_name or project_risk_name:
            parts = [name for name in (project_plan_fact_name, project_risk_name) if name]
            filename = f"reports_executive_{'_'.join(parts[:2])}.csv"
        safe_filename = quote(filename, safe="._-")
        return output.getvalue(), safe_filename

    @staticmethod
    def installers_kpi_export_csv(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
        sort_by: str,
        sort_dir: str,
    ) -> str:
        items = ReportsService.installers_kpi(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "installer_id",
                "installer_name",
                "installed_doors",
                "payroll_total",
                "revenue_total",
                "profit_total",
                "missing_rates_installed_doors",
            ]
        )
        for row in items:
            writer.writerow(
                [
                    str(row.get("installer_id", "")),
                    row.get("installer_name", ""),
                    int(row.get("installed_doors", 0)),
                    row.get("payroll_total", 0),
                    row.get("revenue_total", 0),
                    row.get("profit_total", 0),
                    int(row.get("missing_rates_installed_doors", 0)),
                ]
            )
        return output.getvalue()

    @staticmethod
    def order_numbers_kpi(
        uow,
        *,
        company_id,
        project_id: UUID | None,
        q: str | None,
        limit: int,
        offset: int,
        sort_by: str,
        sort_dir: str,
    ) -> OrderNumbersKpiResponse:
        data = ReportsService.order_numbers_kpi(
            uow.session,
            company_id=company_id,
            project_id=project_id,
            q=q,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        return OrderNumbersKpiResponse(
            total=int(data.get("total", 0)),
            limit=int(data.get("limit", limit)),
            offset=int(data.get("offset", offset)),
            items=[OrderNumberKpiItem(**x) for x in data.get("items", [])],
        )

    @staticmethod
    def order_numbers_kpi_export_csv(
        uow,
        *,
        company_id,
        project_id: UUID | None,
        q: str | None,
        limit: int,
        offset: int,
        sort_by: str,
        sort_dir: str,
    ) -> str:
        data = ReportsService.order_numbers_kpi(
            uow.session,
            company_id=company_id,
            project_id=project_id,
            q=q,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "order_number",
                "total_doors",
                "installed_doors",
                "not_installed_doors",
                "open_issues",
                "planned_revenue_total",
                "installed_revenue_total",
                "payroll_total",
                "profit_total",
                "missing_rates_installed_doors",
                "completion_pct",
            ]
        )
        for row in data.get("items", []):
            writer.writerow(
                [
                    row.get("order_number", ""),
                    int(row.get("total_doors", 0)),
                    int(row.get("installed_doors", 0)),
                    int(row.get("not_installed_doors", 0)),
                    int(row.get("open_issues", 0)),
                    row.get("planned_revenue_total", 0),
                    row.get("installed_revenue_total", 0),
                    row.get("payroll_total", 0),
                    row.get("profit_total", 0),
                    int(row.get("missing_rates_installed_doors", 0)),
                    float(row.get("completion_pct", 0.0)),
                ]
            )
        return output.getvalue()

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
    def project_plan_fact(
        uow,
        *,
        company_id,
        project_id: UUID,
    ) -> ProjectPlanFactResponse:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found",
                details={"project_id": str(project_id)},
            )

        data = ReportsService.project_plan_fact(
            uow.session,
            company_id=company_id,
            project_id=project_id,
        )
        return ProjectPlanFactResponse(project_id=project_id, **data)

    @staticmethod
    def project_risk_drilldown(
        uow,
        *,
        company_id,
        project_id: UUID,
        limit: int,
    ) -> ProjectRiskDrilldownResponse:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found",
                details={"project_id": str(project_id)},
            )

        data = ReportsService.project_risk_drilldown(
            uow.session,
            company_id=company_id,
            project_id=project_id,
            limit=limit,
        )
        summary = dict(data.get("summary", {}))
        drivers = [
            {
                "code": "profit_gap_total",
                "label": "Profit Gap",
                "severity": "DANGER",
                "value": summary.get("profit_gap_total", 0),
            },
            {
                "code": "delayed_profit_total",
                "label": "Delayed Profit",
                "severity": "DANGER",
                "value": summary.get("delayed_profit_total", 0),
            },
            {
                "code": "blocked_issue_profit_at_risk",
                "label": "Blocked Issue Risk",
                "severity": "WARN",
                "value": summary.get("blocked_issue_profit_at_risk", 0),
            },
            {
                "code": "open_issues",
                "label": "Open Issues",
                "severity": "WARN",
                "value": summary.get("open_issues", 0),
            },
            {
                "code": "data_risk",
                "label": "Data Risk",
                "severity": "WARN",
                "value": (
                    int(summary.get("missing_planned_rates_doors", 0) or 0)
                    + int(summary.get("missing_actual_rates_doors", 0) or 0)
                    + int(summary.get("missing_addon_plans_facts", 0) or 0)
                ),
            },
        ]

        return ProjectRiskDrilldownResponse(
            generated_at=datetime.now(timezone.utc),
            project_id=project_id,
            project_name=project.name,
            summary=ProjectRiskDrilldownSummaryResponse(**summary),
            drivers=[
                ProjectRiskDriverItem(**item)
                for item in drivers
            ],
            top_reasons=[
                ProjectRiskReasonItem(**item) for item in data.get("top_reasons", [])
            ],
            risky_orders=[
                ProjectRiskOrderItem(**item) for item in data.get("risky_orders", [])
            ],
        )

    @staticmethod
    def projects_margin(
        uow,
        *,
        company_id,
        limit: int,
        offset: int,
        sort_by: str,
        sort_dir: str,
    ) -> ProjectsMarginResponse:
        data = ReportsService.projects_margin(
            uow.session,
            company_id=company_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        return ProjectsMarginResponse(
            total=int(data.get("total", 0)),
            limit=limit,
            offset=offset,
            items=[ProjectMarginItem(**item) for item in data.get("items", [])],
        )

    @staticmethod
    def issues_addons_impact(
        uow,
        *,
        company_id,
        limit: int,
    ) -> IssuesAddonsImpactResponse:
        now = datetime.now(timezone.utc)
        data = ReportsService.issues_addons_impact(
            uow.session,
            company_id=company_id,
            limit=limit,
        )
        return IssuesAddonsImpactResponse(
            generated_at=now,
            summary=IssuesAddonsImpactSummaryResponse(
                **dict(data.get("summary", {}))
            ),
            top_reasons=[
                IssuesAddonsImpactReasonItem(**item)
                for item in data.get("top_reasons", [])
            ],
            addon_impact=[
                IssuesAddonsImpactAddonItem(**item)
                for item in data.get("addon_impact", [])
            ],
        )

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

    @staticmethod
    def audit_catalog_changes(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
        entity_type: str | None,
        action: str | None,
        limit: int,
        offset: int,
    ) -> AuditCatalogChangesResponse:
        ReportsAdminApiService._validate_audit_catalog_filters(
            entity_type=entity_type,
            action=action,
        )

        data = ReportsService.audit_catalog_changes(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            entity_type=entity_type,
            action=action,
            limit=limit,
            offset=offset,
        )
        return AuditCatalogChangesResponse(
            items=[AuditCatalogChangeItem(**x) for x in data["items"]],
            summary=AuditCatalogChangesSummary(**data["summary"]),
        )

    @staticmethod
    def audit_catalog_changes_export_csv(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
        entity_type: str | None,
        action: str | None,
        limit: int,
    ) -> str:
        ReportsAdminApiService._validate_audit_catalog_filters(
            entity_type=entity_type,
            action=action,
        )
        rows = ReportsService.audit_catalog_changes_export_rows(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            entity_type=entity_type,
            action=action,
            limit=limit,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "created_at",
                "actor_user_id",
                "entity_type",
                "entity_id",
                "action",
                "reason",
                "before",
                "after",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    str(row["id"]),
                    row["created_at"].isoformat(),
                    str(row["actor_user_id"]),
                    row["entity_type"],
                    str(row["entity_id"]),
                    row["action"],
                    row["reason"] or "",
                    (
                        json.dumps(
                            row["before"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if row["before"] is not None
                        else ""
                    ),
                    (
                        json.dumps(
                            row["after"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if row["after"] is not None
                        else ""
                    ),
                ]
            )
        return output.getvalue()

    @staticmethod
    def audit_issue_changes(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        issue_id: UUID | None,
        limit: int,
        offset: int,
    ) -> AuditCatalogChangesResponse:
        ReportsAdminApiService._validate_audit_issue_filters(action=action)
        data = ReportsService.audit_issue_changes(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            issue_id=issue_id,
            limit=limit,
            offset=offset,
        )
        return AuditCatalogChangesResponse(
            items=[AuditCatalogChangeItem(**x) for x in data["items"]],
            summary=AuditCatalogChangesSummary(**data["summary"]),
        )

    @staticmethod
    def audit_issue_changes_export_csv(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        issue_id: UUID | None,
        limit: int,
    ) -> str:
        ReportsAdminApiService._validate_audit_issue_filters(action=action)
        rows = ReportsService.audit_issue_changes_export_rows(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            issue_id=issue_id,
            limit=limit,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "created_at",
                "actor_user_id",
                "entity_type",
                "entity_id",
                "action",
                "reason",
                "before",
                "after",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    str(row["id"]),
                    row["created_at"].isoformat(),
                    str(row["actor_user_id"]),
                    row["entity_type"],
                    str(row["entity_id"]),
                    row["action"],
                    row["reason"] or "",
                    (
                        json.dumps(
                            row["before"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if row["before"] is not None
                        else ""
                    ),
                    (
                        json.dumps(
                            row["after"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if row["after"] is not None
                        else ""
                    ),
                ]
            )
        return output.getvalue()

    @staticmethod
    def audit_installer_rate_changes(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        rate_id: UUID | None,
        limit: int,
        offset: int,
    ) -> AuditCatalogChangesResponse:
        ReportsAdminApiService._validate_audit_installer_rate_filters(action=action)
        data = ReportsService.audit_installer_rate_changes(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            rate_id=rate_id,
            limit=limit,
            offset=offset,
        )
        return AuditCatalogChangesResponse(
            items=[AuditCatalogChangeItem(**x) for x in data["items"]],
            summary=AuditCatalogChangesSummary(**data["summary"]),
        )

    @staticmethod
    def audit_installer_rate_changes_export_csv(
        uow,
        *,
        company_id,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        rate_id: UUID | None,
        limit: int,
    ) -> str:
        ReportsAdminApiService._validate_audit_installer_rate_filters(action=action)
        rows = ReportsService.audit_installer_rate_changes_export_rows(
            uow.session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            rate_id=rate_id,
            limit=limit,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "created_at",
                "actor_user_id",
                "entity_type",
                "entity_id",
                "action",
                "reason",
                "before",
                "after",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    str(row["id"]),
                    row["created_at"].isoformat(),
                    str(row["actor_user_id"]),
                    row["entity_type"],
                    str(row["entity_id"]),
                    row["action"],
                    row["reason"] or "",
                    (
                        json.dumps(
                            row["before"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if row["before"] is not None
                        else ""
                    ),
                    (
                        json.dumps(
                            row["after"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if row["after"] is not None
                        else ""
                    ),
                ]
            )
        return output.getvalue()

    @staticmethod
    def limit_alerts(
        uow,
        *,
        company_id,
        actor_user_id: UUID,
        limit: int,
        offset: int,
    ) -> LimitAlertsResponse:
        audit_repo = getattr(uow, "audit", None)
        if audit_repo is None:
            return LimitAlertsResponse(
                items=[],
                unread_count=0,
                last_read_at=None,
                limit=limit,
                offset=offset,
            )

        cursor = audit_repo.get_alert_read_cursor(
            company_id=company_id,
            user_id=actor_user_id,
        )
        last_read_at = cursor.last_read_at if cursor else None
        items = ReportsService.limit_alerts(
            uow.session,
            company_id=company_id,
            limit=limit,
            offset=offset,
        )
        return LimitAlertsResponse(
            items=[
                LimitAlertItem(
                    **item,
                    is_unread=(
                        last_read_at is None or item["created_at"] > last_read_at
                    ),
                )
                for item in items
            ],
            unread_count=audit_repo.count_limit_alerts_since(
                company_id=company_id,
                since=last_read_at,
            ),
            last_read_at=last_read_at,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def mark_limit_alerts_read(
        uow,
        *,
        company_id,
        actor_user_id: UUID,
        read_up_to: datetime | None,
    ) -> LimitAlertsReadResponse:
        audit_repo = getattr(uow, "audit", None)
        if audit_repo is None:
            return LimitAlertsReadResponse(
                unread_count=0,
                last_read_at=read_up_to or datetime.now(timezone.utc),
            )
        timestamp = read_up_to or datetime.now(timezone.utc)
        cursor = audit_repo.upsert_alert_read_cursor(
            company_id=company_id,
            user_id=actor_user_id,
            last_read_at=timestamp,
        )
        unread_count = audit_repo.count_limit_alerts_since(
            company_id=company_id,
            since=cursor.last_read_at,
        )
        return LimitAlertsReadResponse(
            unread_count=unread_count,
            last_read_at=cursor.last_read_at,
        )

    @staticmethod
    def operations_center(
        uow,
        *,
        company_id,
        actor_user_id: UUID,
    ) -> OperationsCenterResponse:
        now = datetime.now(timezone.utc)
        data = ReportsService.operations_center(
            uow.session,
            company_id=company_id,
            now=now,
        )

        unread_count = 0
        audit_repo = getattr(uow, "audit", None)
        if audit_repo is not None:
            cursor = audit_repo.get_alert_read_cursor(
                company_id=company_id,
                user_id=actor_user_id,
            )
            unread_count = audit_repo.count_limit_alerts_since(
                company_id=company_id,
                since=cursor.last_read_at if cursor else None,
            )

        alerts_payload = dict(data["alerts"])
        alerts_payload["unread_count"] = unread_count

        return OperationsCenterResponse(
            generated_at=now,
            imports=OperationsCenterImportsSummary(**data["imports"]),
            outbox=OperationsCenterOutboxSummary(**data["outbox"]),
            alerts=OperationsCenterAlertsSummary(**alerts_payload),
            top_failing_projects=[
                OperationsCenterFailingProjectItem(**item)
                for item in data["top_failing_projects"]
            ],
        )

    @staticmethod
    def operations_sla(
        uow,
        *,
        company_id,
        actor_user_id: UUID,
    ) -> OperationsSlaResponse:
        now = datetime.now(timezone.utc)
        center = ReportsService.operations_center(
            uow.session,
            company_id=company_id,
            now=now,
        )
        sync_health = SyncHealthService.run_for_company(
            uow,
            company_id=company_id,
        )

        imports = center["imports"]
        outbox = center["outbox"]
        alerts = center["alerts"]
        sync_counts = sync_health.get("counts") or {}

        risky_import_runs = int(imports.get("failed_runs", 0)) + int(
            imports.get("partial_runs", 0)
        )
        active_import_runs = int(imports.get("import_runs", 0)) + int(
            imports.get("retry_runs", 0)
        )
        import_failure_rate = (
            (risky_import_runs / active_import_runs) * 100.0
            if active_import_runs > 0
            else 0.0
        )

        outbox_total = int(outbox.get("total", 0))
        outbox_failed_total = int(outbox.get("failed_total", 0))
        outbox_failed_rate = (
            (outbox_failed_total / outbox_total) * 100.0 if outbox_total > 0 else 0.0
        )
        outbox_pending_overdue = float(outbox.get("pending_overdue_15m", 0))
        alerts_danger_24h = float(alerts.get("danger_last_24h", 0))
        sync_danger_installers = float(sync_counts.get("danger", 0))

        metric_rows = [
            {
                "code": "imports_failure_rate_24h",
                "title": "Import Failure Rate (24h)",
                "unit": "pct",
                "current": round(import_failure_rate, 2),
                "target": 5.0,
                "warn_threshold": 15.0,
                "danger_threshold": 30.0,
            },
            {
                "code": "outbox_failed_rate",
                "title": "Outbox Failed Rate",
                "unit": "pct",
                "current": round(outbox_failed_rate, 2),
                "target": 2.0,
                "warn_threshold": 5.0,
                "danger_threshold": 15.0,
            },
            {
                "code": "outbox_pending_overdue_15m",
                "title": "Outbox Pending >15m",
                "unit": "count",
                "current": float(outbox_pending_overdue),
                "target": 5.0,
                "warn_threshold": 20.0,
                "danger_threshold": 50.0,
            },
            {
                "code": "limit_alerts_danger_24h",
                "title": "Limit Danger Alerts (24h)",
                "unit": "count",
                "current": float(alerts_danger_24h),
                "target": 0.0,
                "warn_threshold": 1.0,
                "danger_threshold": 3.0,
            },
            {
                "code": "sync_danger_installers",
                "title": "Sync Danger Installers",
                "unit": "count",
                "current": float(sync_danger_installers),
                "target": 0.0,
                "warn_threshold": 1.0,
                "danger_threshold": 3.0,
            },
        ]

        metrics: list[OperationsSlaMetricResponse] = []
        statuses: list[str] = []
        for row in metric_rows:
            status = ReportsAdminApiService._metric_status(
                value=float(row["current"]),
                warn=float(row["warn_threshold"]),
                danger=float(row["danger_threshold"]),
            )
            statuses.append(status)
            metrics.append(
                OperationsSlaMetricResponse(
                    **row,
                    status=status,
                )
            )

        overall_status = ReportsAdminApiService._overall_status(statuses)
        playbooks: list[OperationsSlaPlaybookResponse] = []

        metric_map = {x.code: x for x in metrics}
        imports_metric = metric_map["imports_failure_rate_24h"]
        if imports_metric.status in {"WARN", "DANGER"}:
            playbooks.append(
                OperationsSlaPlaybookResponse(
                    code="PLAYBOOK_IMPORTS_RETRY_FAILED",
                    severity=imports_metric.status,
                    title="Retry failed imports in bulk",
                    description="Open Projects with failed runs preselected and retry only failed entries.",
                    action_url="/projects?only_failed_runs=1",
                )
            )
        outbox_rate_metric = metric_map["outbox_failed_rate"]
        overdue_metric = metric_map["outbox_pending_overdue_15m"]
        if outbox_rate_metric.status in {"WARN", "DANGER"} or overdue_metric.status in {
            "WARN",
            "DANGER",
        }:
            playbooks.append(
                OperationsSlaPlaybookResponse(
                    code="PLAYBOOK_OUTBOX_TRIAGE",
                    severity=(
                        "DANGER"
                        if "DANGER" in {outbox_rate_metric.status, overdue_metric.status}
                        else "WARN"
                    ),
                    title="Triage outbox failures",
                    description="Review failed queue and trigger controlled retries from Reports/Projects.",
                    action_url="/reports",
                )
            )
        limit_metric = metric_map["limit_alerts_danger_24h"]
        if limit_metric.status in {"WARN", "DANGER"}:
            playbooks.append(
                OperationsSlaPlaybookResponse(
                    code="PLAYBOOK_LIMIT_CAPACITY",
                    severity=limit_metric.status,
                    title="Resolve plan limit pressure",
                    description="Review plan limits and reduce pressure on users/projects/doors quotas.",
                    action_url="/settings",
                )
            )
        sync_metric = metric_map["sync_danger_installers"]
        if sync_metric.status in {"WARN", "DANGER"}:
            playbooks.append(
                OperationsSlaPlaybookResponse(
                    code="PLAYBOOK_SYNC_RECOVERY",
                    severity=sync_metric.status,
                    title="Recover sync-danger installers",
                    description="Inspect sync health and recover installers with high lag/offline days.",
                    action_url="/dashboard",
                )
            )

        if not playbooks:
            playbooks.append(
                OperationsSlaPlaybookResponse(
                    code="PLAYBOOK_KEEP_STABLE",
                    severity="OK",
                    title="Maintain current SLA",
                    description="No immediate action required. Keep monitoring operations center KPIs.",
                    action_url="/reports",
                )
            )

        del actor_user_id
        return OperationsSlaResponse(
            generated_at=now,
            overall_status=overall_status,
            metrics=metrics,
            playbooks=playbooks,
        )

    @staticmethod
    def operations_sla_history(
        uow,
        *,
        company_id,
        actor_user_id: UUID,
        days: int,
    ) -> OperationsSlaHistoryResponse:
        now = datetime.now(timezone.utc)
        raw = ReportsService.operations_sla_history(
            uow.session,
            company_id=company_id,
            now=now,
            days=days,
        )

        points: list[OperationsSlaHistoryPointResponse] = []
        status_days = {"OK": 0, "WARN": 0, "DANGER": 0}

        for row in raw.get("points", []):
            import_status = ReportsAdminApiService._metric_status(
                value=float(row["import_failure_rate_pct"]),
                warn=15.0,
                danger=30.0,
            )
            outbox_status = ReportsAdminApiService._metric_status(
                value=float(row["outbox_failed_rate_pct"]),
                warn=5.0,
                danger=15.0,
            )
            alerts_status = ReportsAdminApiService._metric_status(
                value=float(row["danger_alerts_count"]),
                warn=1.0,
                danger=3.0,
            )
            overall_status = ReportsAdminApiService._overall_status(
                [import_status, outbox_status, alerts_status]
            )
            status_days[overall_status] += 1
            points.append(
                OperationsSlaHistoryPointResponse(
                    day=row["day"],
                    overall_status=overall_status,
                    import_status=import_status,
                    outbox_status=outbox_status,
                    alerts_status=alerts_status,
                    import_runs=int(row["import_runs"]),
                    risky_import_runs=int(row["risky_import_runs"]),
                    import_failure_rate_pct=float(row["import_failure_rate_pct"]),
                    outbox_total=int(row["outbox_total"]),
                    outbox_failed=int(row["outbox_failed"]),
                    outbox_failed_rate_pct=float(row["outbox_failed_rate_pct"]),
                    danger_alerts_count=int(row["danger_alerts_count"]),
                )
            )

        current_status = points[-1].overall_status if points else "OK"
        delta_import_failure_rate_pct = 0.0
        delta_outbox_failed_rate_pct = 0.0
        delta_danger_alerts_count = 0
        if len(points) >= 2:
            prev = points[-2]
            cur = points[-1]
            delta_import_failure_rate_pct = round(
                float(cur.import_failure_rate_pct) - float(prev.import_failure_rate_pct), 2
            )
            delta_outbox_failed_rate_pct = round(
                float(cur.outbox_failed_rate_pct) - float(prev.outbox_failed_rate_pct), 2
            )
            delta_danger_alerts_count = int(cur.danger_alerts_count - prev.danger_alerts_count)

        del actor_user_id
        return OperationsSlaHistoryResponse(
            generated_at=now,
            days=int(raw.get("days", days)),
            points=points,
            summary=OperationsSlaHistorySummaryResponse(
                ok_days=int(status_days["OK"]),
                warn_days=int(status_days["WARN"]),
                danger_days=int(status_days["DANGER"]),
                current_status=current_status,
                delta_import_failure_rate_pct=delta_import_failure_rate_pct,
                delta_outbox_failed_rate_pct=delta_outbox_failed_rate_pct,
                delta_danger_alerts_count=delta_danger_alerts_count,
            ),
        )

    @staticmethod
    def issues_analytics(
        uow,
        *,
        company_id,
        actor_user_id: UUID,
        days: int,
    ) -> IssuesAnalyticsResponse:
        now = datetime.now(timezone.utc)
        data = ReportsService.issues_analytics(
            uow.session,
            company_id=company_id,
            now=now,
            days=days,
        )
        del actor_user_id
        return IssuesAnalyticsResponse(
            generated_at=now,
            days=int(data.get("days", days)),
            summary=IssuesAnalyticsSummaryResponse(**dict(data.get("summary", {}))),
            trend=[
                IssuesAnalyticsTrendPointResponse(**item)
                for item in list(data.get("trend", []))
            ],
        )
