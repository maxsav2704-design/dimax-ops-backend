from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class KpiResponse(BaseModel):
    period_from: datetime | None
    period_to: datetime | None

    installed_doors: int
    not_installed_doors: int

    payroll_total: Decimal
    revenue_total: Decimal
    profit_total: Decimal

    problem_projects: int

    missing_rates_installed_doors: int
    missing_addon_plans_done: int


class LimitMetricResponse(BaseModel):
    current: int
    max: int | None
    utilization_pct: float | None
    is_enforced: bool
    is_exceeded: bool


class LimitsKpiResponse(BaseModel):
    plan_code: str | None
    plan_active: bool | None
    total_doors: int
    users: LimitMetricResponse
    admin_users: LimitMetricResponse | None = None
    installer_users: LimitMetricResponse | None = None
    installers: LimitMetricResponse
    projects: LimitMetricResponse
    doors_per_project: LimitMetricResponse


class DashboardResponse(BaseModel):
    kpi: KpiResponse
    sync_health: dict
    limits: LimitsKpiResponse


class DispatcherBoardSummaryResponse(BaseModel):
    total_projects: int
    total_doors: int
    installed_doors: int
    pending_doors: int
    projects_needing_dispatch: int
    open_issues: int
    blocked_issues: int
    unassigned_doors: int
    available_installers: int
    busy_installers: int
    scheduled_visits_7d: int


class DispatcherProjectInstallerRecommendationItem(BaseModel):
    installer_id: UUID
    installer_name: str
    availability_band: str
    active_projects: int
    assigned_open_doors: int
    open_issues: int
    next_event_at: datetime | None


class DispatcherProjectItem(BaseModel):
    project_id: UUID
    project_name: str
    address: str
    project_status: str
    dispatch_status: str
    contact_name: str | None
    total_doors: int
    installed_doors: int
    pending_doors: int
    assigned_open_doors: int
    unassigned_doors: int
    open_issues: int
    blocked_issues: int
    completion_pct: float
    next_visit_at: datetime | None
    next_visit_title: str | None
    recommended_installers: list[DispatcherProjectInstallerRecommendationItem]


class DispatcherInstallerItem(BaseModel):
    installer_id: UUID
    installer_name: str
    status: str
    availability_band: str
    is_active: bool
    phone: str | None
    email: str | None
    active_projects: int
    assigned_open_doors: int
    open_issues: int
    next_event_at: datetime | None
    next_event_title: str | None


class DispatcherBoardResponse(BaseModel):
    generated_at: datetime
    summary: DispatcherBoardSummaryResponse
    projects: list[DispatcherProjectItem]
    installers: list[DispatcherInstallerItem]


class ProblemProjectItem(BaseModel):
    project_id: UUID
    name: str
    address: str
    not_installed_doors: int


class ProblemProjectsResponse(BaseModel):
    items: list[ProblemProjectItem]


class TopReasonItem(BaseModel):
    reason_id: UUID | None
    reason_name: str
    count: int


class TopReasonsResponse(BaseModel):
    items: list[TopReasonItem]


class InstallerKpiItem(BaseModel):
    installer_id: UUID
    installer_name: str
    installed_doors: int
    payroll_total: Decimal
    revenue_total: Decimal
    profit_total: Decimal
    missing_rates_installed_doors: int


class InstallersKpiResponse(BaseModel):
    period_from: datetime | None
    period_to: datetime | None
    items: list[InstallerKpiItem]


class InstallerProfitabilityMatrixItem(BaseModel):
    installer_id: UUID
    installer_name: str
    performance_band: str
    installed_doors: int
    active_projects: int
    open_issues: int
    addons_done_qty: Decimal
    revenue_total: Decimal
    payroll_total: Decimal
    profit_total: Decimal
    margin_pct: float
    avg_profit_per_door: Decimal
    missing_rates_installed_doors: int
    missing_addon_plans_facts: int
    last_installed_at: datetime | None


class InstallerProfitabilityMatrixResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[InstallerProfitabilityMatrixItem]


class InstallerProjectProfitabilityItem(BaseModel):
    installer_id: UUID
    installer_name: str
    project_id: UUID
    project_name: str
    performance_band: str
    installed_doors: int
    open_issues: int
    addons_done_qty: Decimal
    revenue_total: Decimal
    payroll_total: Decimal
    profit_total: Decimal
    margin_pct: float
    avg_profit_per_door: Decimal
    missing_rates_installed_doors: int
    missing_addon_plans_facts: int
    last_installed_at: datetime | None


class InstallerProjectProfitabilityResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[InstallerProjectProfitabilityItem]


class InstallerKpiProjectItem(BaseModel):
    project_id: UUID
    project_name: str
    installed_doors: int
    open_issues: int
    revenue_total: Decimal
    payroll_total: Decimal
    profit_total: Decimal
    last_installed_at: datetime | None


class InstallerKpiOrderItem(BaseModel):
    order_number: str
    installed_doors: int
    revenue_total: Decimal
    payroll_total: Decimal
    profit_total: Decimal


class InstallerKpiDetailsResponse(BaseModel):
    installer_id: UUID
    installer_name: str
    installed_doors: int
    active_projects: int
    order_numbers: int
    open_issues: int
    addons_done_qty: Decimal
    addon_revenue_total: Decimal
    addon_payroll_total: Decimal
    addon_profit_total: Decimal
    revenue_total: Decimal
    payroll_total: Decimal
    profit_total: Decimal
    missing_rates_installed_doors: int
    missing_addon_plans_facts: int
    last_installed_at: datetime | None
    top_projects: list[InstallerKpiProjectItem]
    order_breakdown: list[InstallerKpiOrderItem]


class OrderNumberKpiItem(BaseModel):
    order_number: str
    total_doors: int
    installed_doors: int
    not_installed_doors: int
    open_issues: int
    planned_revenue_total: Decimal
    installed_revenue_total: Decimal
    payroll_total: Decimal
    profit_total: Decimal
    missing_rates_installed_doors: int
    completion_pct: float


class OrderNumbersKpiResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[OrderNumberKpiItem]


class ProjectProfitResponse(BaseModel):
    project_id: UUID
    installed_doors: int
    payroll_total: Decimal
    revenue_total: Decimal
    profit_total: Decimal
    missing_rates_installed_doors: int


class ProjectPlanFactResponse(BaseModel):
    project_id: UUID
    total_doors: int
    installed_doors: int
    not_installed_doors: int
    completion_pct: float
    open_issues: int
    planned_revenue_total: Decimal
    actual_revenue_total: Decimal
    revenue_gap_total: Decimal
    planned_payroll_total: Decimal
    actual_payroll_total: Decimal
    payroll_gap_total: Decimal
    planned_profit_total: Decimal
    actual_profit_total: Decimal
    profit_gap_total: Decimal
    planned_addons_qty: Decimal
    actual_addons_qty: Decimal
    missing_planned_rates_doors: int
    missing_actual_rates_doors: int
    missing_addon_plans_facts: int


class ProjectMarginItem(BaseModel):
    project_id: UUID
    project_name: str
    project_status: str
    total_doors: int
    installed_doors: int
    completion_pct: float
    open_issues: int
    revenue_total: Decimal
    payroll_total: Decimal
    profit_total: Decimal
    margin_pct: float
    missing_rates_installed_doors: int
    missing_addon_plans_facts: int
    last_installed_at: datetime | None


class ProjectsMarginResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ProjectMarginItem]


class RiskConcentrationSummaryResponse(BaseModel):
    open_issue_profit_at_risk: Decimal
    blocked_issue_profit_at_risk: Decimal
    delayed_profit_total: Decimal
    risky_projects: int
    risky_orders: int
    risky_installers: int
    worst_project_profit_total: Decimal
    worst_order_profit_total: Decimal
    worst_installer_profit_total: Decimal


class RiskConcentrationResponse(BaseModel):
    generated_at: datetime
    summary: RiskConcentrationSummaryResponse
    projects: list[ProjectMarginItem]
    orders: list[OrderNumberKpiItem]
    installers: list[InstallerProfitabilityMatrixItem]


class ProjectRiskDriverItem(BaseModel):
    code: str
    label: str
    severity: str
    value: Decimal


class ProjectRiskReasonItem(BaseModel):
    reason_id: UUID | None
    reason_name: str
    doors: int
    revenue_delayed_total: Decimal
    profit_delayed_total: Decimal


class ProjectRiskOrderItem(BaseModel):
    order_number: str
    total_doors: int
    installed_doors: int
    not_installed_doors: int
    open_issues: int
    planned_revenue_total: Decimal
    actual_revenue_total: Decimal
    revenue_gap_total: Decimal
    actual_profit_total: Decimal
    completion_pct: float


class ProjectRiskDrilldownSummaryResponse(BaseModel):
    total_doors: int
    installed_doors: int
    not_installed_doors: int
    completion_pct: float
    open_issues: int
    blocked_open_issues: int
    planned_revenue_total: Decimal
    actual_revenue_total: Decimal
    revenue_gap_total: Decimal
    planned_profit_total: Decimal
    actual_profit_total: Decimal
    profit_gap_total: Decimal
    actual_margin_pct: float
    delayed_revenue_total: Decimal
    delayed_profit_total: Decimal
    blocked_issue_profit_at_risk: Decimal
    addon_revenue_total: Decimal
    addon_profit_total: Decimal
    missing_planned_rates_doors: int
    missing_actual_rates_doors: int
    missing_addon_plans_facts: int


class ProjectRiskDrilldownResponse(BaseModel):
    generated_at: datetime
    project_id: UUID
    project_name: str
    summary: ProjectRiskDrilldownSummaryResponse
    drivers: list[ProjectRiskDriverItem]
    top_reasons: list[ProjectRiskReasonItem]
    risky_orders: list[ProjectRiskOrderItem]


class IssuesAddonsImpactSummaryResponse(BaseModel):
    open_issues: int
    blocked_open_issues: int
    not_installed_doors: int
    open_issue_revenue_at_risk: Decimal
    open_issue_payroll_at_risk: Decimal
    open_issue_profit_at_risk: Decimal
    blocked_issue_profit_at_risk: Decimal
    delayed_revenue_total: Decimal
    delayed_payroll_total: Decimal
    delayed_profit_total: Decimal
    addon_revenue_total: Decimal
    addon_payroll_total: Decimal
    addon_profit_total: Decimal
    missing_addon_plans_facts: int


class IssuesAddonsImpactReasonItem(BaseModel):
    reason_id: UUID | None
    reason_name: str
    doors: int
    revenue_delayed_total: Decimal
    payroll_delayed_total: Decimal
    profit_delayed_total: Decimal


class IssuesAddonsImpactAddonItem(BaseModel):
    addon_type_id: UUID | None
    addon_name: str
    qty_done: Decimal
    revenue_total: Decimal
    payroll_total: Decimal
    profit_total: Decimal
    missing_plan_facts: int


class IssuesAddonsImpactResponse(BaseModel):
    generated_at: datetime
    summary: IssuesAddonsImpactSummaryResponse
    top_reasons: list[IssuesAddonsImpactReasonItem]
    addon_impact: list[IssuesAddonsImpactAddonItem]


class DeliveryStatsResponse(BaseModel):
    period_from: datetime | None
    period_to: datetime | None

    whatsapp_pending: int
    whatsapp_delivered: int
    whatsapp_failed: int

    email_sent: int
    email_failed: int


class AuditCatalogChangeItem(BaseModel):
    id: UUID
    created_at: datetime
    actor_user_id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    reason: str | None
    before: dict | None
    after: dict | None


class AuditCatalogChangesSummary(BaseModel):
    total: int
    by_entity: dict[str, int]
    by_action: dict[str, int]


class AuditCatalogChangesResponse(BaseModel):
    items: list[AuditCatalogChangeItem]
    summary: AuditCatalogChangesSummary


class LimitAlertItem(BaseModel):
    id: UUID
    created_at: datetime
    action: str
    level: str
    metric: str | None
    current: int | None
    max: int | None
    utilization_pct: float | None
    plan_code: str | None
    is_unread: bool


class LimitAlertsResponse(BaseModel):
    items: list[LimitAlertItem]
    unread_count: int
    last_read_at: datetime | None
    limit: int
    offset: int


class LimitAlertsReadRequest(BaseModel):
    read_up_to: datetime | None = None


class LimitAlertsReadResponse(BaseModel):
    unread_count: int
    last_read_at: datetime


class OperationsCenterImportsSummary(BaseModel):
    window_hours: int
    total_runs: int
    analyze_runs: int
    import_runs: int
    retry_runs: int
    success_runs: int
    partial_runs: int
    failed_runs: int
    empty_runs: int


class OperationsCenterFailingProjectItem(BaseModel):
    project_id: UUID
    project_name: str
    failure_runs: int
    last_run_at: datetime
    last_error: str | None


class OperationsCenterOutboxSummary(BaseModel):
    total: int
    failed_total: int
    pending_overdue_15m: int
    by_channel: dict[str, int]


class OperationsCenterAlertsSummary(BaseModel):
    unread_count: int
    total_last_24h: int
    warn_last_24h: int
    danger_last_24h: int
    latest_created_at: datetime | None


class OperationsCenterResponse(BaseModel):
    generated_at: datetime
    imports: OperationsCenterImportsSummary
    outbox: OperationsCenterOutboxSummary
    alerts: OperationsCenterAlertsSummary
    top_failing_projects: list[OperationsCenterFailingProjectItem]


class OperationsSlaMetricResponse(BaseModel):
    code: str
    title: str
    unit: str
    current: float
    target: float
    warn_threshold: float
    danger_threshold: float
    status: str


class OperationsSlaPlaybookResponse(BaseModel):
    code: str
    severity: str
    title: str
    description: str
    action_url: str


class OperationsSlaResponse(BaseModel):
    generated_at: datetime
    overall_status: str
    metrics: list[OperationsSlaMetricResponse]
    playbooks: list[OperationsSlaPlaybookResponse]


class OperationsSlaHistoryPointResponse(BaseModel):
    day: date
    overall_status: str
    import_status: str
    outbox_status: str
    alerts_status: str
    import_runs: int
    risky_import_runs: int
    import_failure_rate_pct: float
    outbox_total: int
    outbox_failed: int
    outbox_failed_rate_pct: float
    danger_alerts_count: int


class OperationsSlaHistorySummaryResponse(BaseModel):
    ok_days: int
    warn_days: int
    danger_days: int
    current_status: str
    delta_import_failure_rate_pct: float
    delta_outbox_failed_rate_pct: float
    delta_danger_alerts_count: int


class OperationsSlaHistoryResponse(BaseModel):
    generated_at: datetime
    days: int
    points: list[OperationsSlaHistoryPointResponse]
    summary: OperationsSlaHistorySummaryResponse


class IssuesAnalyticsSummaryResponse(BaseModel):
    total_issues: int
    open_issues: int
    closed_issues: int
    overdue_open_issues: int
    blocked_open_issues: int
    p1_open_issues: int
    overdue_open_rate_pct: float
    mttr_hours: float
    mttr_p50_hours: float
    mttr_sample_size: int
    backlog_by_workflow: dict[str, int]
    backlog_by_priority: dict[str, int]


class IssuesAnalyticsTrendPointResponse(BaseModel):
    day: date
    opened: int
    closed: int
    backlog_open_end: int


class IssuesAnalyticsResponse(BaseModel):
    generated_at: datetime
    days: int
    summary: IssuesAnalyticsSummaryResponse
    trend: list[IssuesAnalyticsTrendPointResponse]
