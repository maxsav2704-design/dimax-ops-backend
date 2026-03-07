from __future__ import annotations


def _find_first_ref(node):
    if isinstance(node, dict):
        ref = node.get("$ref")
        if ref:
            return ref
        for value in node.values():
            found = _find_first_ref(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_first_ref(value)
            if found:
                return found
    return None


def _response_ref(spec: dict, *, path: str, method: str, status: str = "200") -> str | None:
    schema = (
        spec["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]
    )
    return _find_first_ref(schema)


def _response_schema(
    spec: dict,
    *,
    path: str,
    method: str,
    content_type: str,
    status: str = "200",
) -> dict:
    return spec["paths"][path][method]["responses"][status]["content"][content_type]["schema"]


def _assert_no_content_response(
    spec: dict,
    *,
    path: str,
    method: str,
    status: str = "204",
) -> None:
    response = spec["paths"][path][method]["responses"][status]
    content = response.get("content")
    assert not content


def _response_statuses(spec: dict, *, path: str, method: str) -> set[str]:
    return set(spec["paths"][path][method]["responses"].keys())


def _response_description(
    spec: dict,
    *,
    path: str,
    method: str,
    status: str,
) -> str | None:
    return spec["paths"][path][method]["responses"][status].get("description")


def test_openapi_contract_for_key_endpoints(client_raw):
    resp = client_raw.get("/openapi.json")
    assert resp.status_code == 200, resp.text
    spec = resp.json()

    assert _response_ref(
        spec,
        path="/api/v1/auth/login",
        method="post",
    ) == "#/components/schemas/TokenPair"
    assert _response_ref(
        spec,
        path="/api/v1/auth/refresh",
        method="post",
    ) == "#/components/schemas/TokenPair"
    assert _response_ref(
        spec,
        path="/api/v1/auth/logout",
        method="post",
    ) == "#/components/schemas/LogoutResponse"
    assert _response_ref(
        spec,
        path="/api/v1/auth/logout-refresh",
        method="post",
    ) == "#/components/schemas/LogoutRefreshResponse"
    assert _response_ref(
        spec,
        path="/api/v1/auth/logout-all",
        method="post",
    ) == "#/components/schemas/LogoutAllResponse"
    assert _response_ref(
        spec,
        path="/api/v1/auth/me",
        method="get",
    ) == "#/components/schemas/AuthMeResponse"
    assert _response_ref(
        spec,
        path="/api/v1/platform/companies",
        method="get",
    ) == "#/components/schemas/PlatformCompanyListResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/platform/companies",
        method="post",
        status="201",
    ) == "#/components/schemas/PlatformCompanyCreateResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/platform/companies/{company_id}/status",
        method="patch",
    ) == "#/components/schemas/PlatformCompanyDTO"
    assert _response_ref(
        spec,
        path="/api/v1/platform/companies/{company_id}/plan",
        method="get",
    ) == "#/components/schemas/PlatformCompanyPlanDTO"
    assert _response_ref(
        spec,
        path="/api/v1/platform/companies/{company_id}/plan",
        method="put",
    ) == "#/components/schemas/PlatformCompanyPlanDTO"
    assert _response_ref(
        spec,
        path="/api/v1/platform/companies/{company_id}/usage",
        method="get",
    ) == "#/components/schemas/PlatformCompanyUsageDTO"
    assert _response_ref(
        spec,
        path="/api/v1/platform/companies/{company_id}/users",
        method="post",
        status="201",
    ) == "#/components/schemas/PlatformCompanyUserDTO"

    assert _response_ref(
        spec,
        path="/api/v1/admin/installers",
        method="get",
    ) == "#/components/schemas/InstallerDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installers/{installer_id}",
        method="get",
    ) == "#/components/schemas/InstallerDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installers",
        method="post",
        status="201",
    ) == "#/components/schemas/InstallerDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installers/{installer_id}/link-user",
        method="post",
    ) == "#/components/schemas/InstallerDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installers/{installer_id}/link-user",
        method="delete",
    ) == "#/components/schemas/InstallerDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installers/{installer_id}/link-user",
        method="post",
        status="400",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installers/{installer_id}/link-user",
        method="post",
        status="404",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installers/{installer_id}/link-user",
        method="post",
        status="409",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    _assert_no_content_response(
        spec,
        path="/api/v1/admin/installers/{installer_id}",
        method="delete",
    )

    assert _response_ref(
        spec,
        path="/api/v1/admin/projects",
        method="get",
    ) == "#/components/schemas/ProjectListResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/{project_id}",
        method="get",
    ) == "#/components/schemas/ProjectDetailsResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/{project_id}/addons",
        method="get",
    ) == "#/components/schemas/ProjectAddonsResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/{project_id}/addons/plan",
        method="put",
    ) == "#/components/schemas/ProjectAddonsResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/{project_id}/addons/plan/{addon_type_id}",
        method="delete",
    ) == "#/components/schemas/OkResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects",
        method="post",
    ) == "#/components/schemas/ProjectCreateResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/{project_id}/doors/import",
        method="post",
    ) == "#/components/schemas/ImportDoorsResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/{project_id}/doors/import-file",
        method="post",
    ) == "#/components/schemas/ImportDoorsFromFileResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/import-mapping-profiles",
        method="get",
    ) == "#/components/schemas/ImportMappingProfilesResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/{project_id}/doors/import-history",
        method="get",
    ) == "#/components/schemas/ProjectImportRunsResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/{project_id}/doors/import-runs/{run_id}/retry",
        method="post",
    ) == "#/components/schemas/ImportDoorsFromFileResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/import-runs/reconcile-latest",
        method="post",
    ) == "#/components/schemas/ProjectBulkImportReconcileResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/import-runs/failed-queue",
        method="get",
    ) == "#/components/schemas/FailedImportRunsQueueResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/import-runs/retry-failed",
        method="post",
    ) == "#/components/schemas/RetryFailedImportRunsResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/{project_id}/doors/import-upload",
        method="post",
    ) == "#/components/schemas/ImportDoorsFromFileResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/projects/{project_id}/doors/layout",
        method="get",
    ) == "#/components/schemas/ProjectDoorsLayoutResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/issues",
        method="get",
    ) == "#/components/schemas/AdminIssuesListResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/issues/{issue_id}",
        method="get",
    ) == "#/components/schemas/AdminIssueDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/issues/{issue_id}/status",
        method="patch",
    ) == "#/components/schemas/AdminIssueDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/issues/{issue_id}/workflow",
        method="patch",
    ) == "#/components/schemas/AdminIssueDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/issues/workflow/bulk",
        method="patch",
    ) == "#/components/schemas/AdminIssuesBulkWorkflowUpdateResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installer-rates",
        method="post",
        status="400",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installer-rates",
        method="post",
        status="409",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installer-rates/bulk",
        method="post",
    ) == "#/components/schemas/InstallerRatesBulkResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installer-rates/timeline",
        method="get",
    ) == "#/components/schemas/InstallerRateTimelineResponse"

    _assert_no_content_response(
        spec,
        path="/api/v1/admin/installer-rates/{rate_id}",
        method="delete",
    )
    assert _response_ref(
        spec,
        path="/api/v1/admin/installer-rates/{rate_id}",
        method="get",
        status="404",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/door-types",
        method="get",
    ) == "#/components/schemas/DoorTypeDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reasons",
        method="get",
    ) == "#/components/schemas/ReasonDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/door-types/export",
        method="get",
    ) == "#/components/schemas/DoorTypesExportResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/door-types/import",
        method="post",
    ) == "#/components/schemas/DoorTypesImportResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/door-types/bulk",
        method="post",
    ) == "#/components/schemas/DoorTypesBulkResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reasons/export",
        method="get",
    ) == "#/components/schemas/ReasonsExportResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reasons/import",
        method="post",
    ) == "#/components/schemas/ReasonsImportResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reasons/bulk",
        method="post",
    ) == "#/components/schemas/ReasonsBulkResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/settings/company",
        method="get",
    ) == "#/components/schemas/CompanySettingsDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/settings/integrations",
        method="get",
    ) == "#/components/schemas/IntegrationsSettingsDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/settings/integrations/health",
        method="get",
    ) == "#/components/schemas/IntegrationsHealthResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/settings/integrations/test-email",
        method="post",
    ) == "#/components/schemas/IntegrationTestSendResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/settings/integrations/test-whatsapp",
        method="post",
    ) == "#/components/schemas/IntegrationTestSendResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/settings/communication-templates",
        method="get",
    ) == "#/components/schemas/CommunicationTemplatesResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/settings/communication-templates",
        method="post",
        status="201",
    ) == "#/components/schemas/CommunicationTemplateDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/settings/communication-templates/{template_id}",
        method="patch",
    ) == "#/components/schemas/CommunicationTemplateDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/settings/communication-templates/render-preview",
        method="post",
    ) == "#/components/schemas/CommunicationTemplateRenderPreviewResponse"
    _assert_no_content_response(
        spec,
        path="/api/v1/admin/settings/communication-templates/{template_id}",
        method="delete",
    )
    _assert_no_content_response(
        spec,
        path="/api/v1/admin/door-types/{door_type_id}",
        method="delete",
    )
    _assert_no_content_response(
        spec,
        path="/api/v1/admin/reasons/{reason_id}",
        method="delete",
    )

    assert _response_ref(
        spec,
        path="/api/v1/admin/calendar/events",
        method="post",
    ) == "#/components/schemas/EventCreateResponse"

    assert _response_ref(
        spec,
        path="/api/v1/admin/journals",
        method="post",
    ) == "#/components/schemas/JournalCreateResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/journals/{journal_id}/mark-ready",
        method="post",
    ) == "#/components/schemas/JournalMarkReadyResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/journals/{journal_id}/export-pdf",
        method="post",
    ) == "#/components/schemas/JournalExportPdfResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/journals/{journal_id}/send",
        method="post",
    ) == "#/components/schemas/SendJournalResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/journals/{journal_id}/pdf/share",
        method="post",
    ) == "#/components/schemas/SharePdfResponse"

    assert _response_ref(
        spec,
        path="/api/v1/admin/dashboard",
        method="get",
    ) == "#/components/schemas/DashboardResponseDTO"

    assert _response_ref(
        spec,
        path="/api/v1/admin/sync/health/run",
        method="post",
    ) == "#/components/schemas/SyncHealthRunResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/sync/health/summary",
        method="get",
    ) == "#/components/schemas/SyncHealthSummaryDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/sync/reset/{installer_id}",
        method="post",
    ) == "#/components/schemas/SyncResetLegacyResponse"

    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/kpi",
        method="get",
    ) == "#/components/schemas/KpiResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/installers-kpi",
        method="get",
    ) == "#/components/schemas/InstallersKpiResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/installers-profitability-matrix",
        method="get",
    ) == "#/components/schemas/InstallerProfitabilityMatrixResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/installer-project-profitability",
        method="get",
    ) == "#/components/schemas/InstallerProjectProfitabilityResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/installers-kpi/{installer_id}",
        method="get",
    ) == "#/components/schemas/InstallerKpiDetailsResponse"
    installers_export_schema = _response_schema(
        spec,
        path="/api/v1/admin/reports/installers-kpi/export",
        method="get",
        content_type="text/csv",
    )
    assert installers_export_schema.get("type") == "string"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/order-numbers-kpi",
        method="get",
    ) == "#/components/schemas/OrderNumbersKpiResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/project-plan-fact/{project_id}",
        method="get",
    ) == "#/components/schemas/ProjectPlanFactResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/project-risk-drilldown/{project_id}",
        method="get",
    ) == "#/components/schemas/ProjectRiskDrilldownResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/projects-margin",
        method="get",
    ) == "#/components/schemas/ProjectsMarginResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/issues-addons-impact",
        method="get",
    ) == "#/components/schemas/IssuesAddonsImpactResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/risk-concentration",
        method="get",
    ) == "#/components/schemas/RiskConcentrationResponse"
    executive_export_schema = _response_schema(
        spec,
        path="/api/v1/admin/reports/executive/export",
        method="get",
        content_type="text/csv",
    )
    assert executive_export_schema.get("type") == "string"
    order_numbers_export_schema = _response_schema(
        spec,
        path="/api/v1/admin/reports/order-numbers-kpi/export",
        method="get",
        content_type="text/csv",
    )
    assert order_numbers_export_schema.get("type") == "string"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/dashboard",
        method="get",
    ) == "#/components/schemas/DashboardResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/dispatcher-board",
        method="get",
    ) == "#/components/schemas/DispatcherBoardResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/limits",
        method="get",
    ) == "#/components/schemas/LimitsKpiResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/limit-alerts",
        method="get",
    ) == "#/components/schemas/LimitAlertsResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/limit-alerts/read",
        method="post",
    ) == "#/components/schemas/LimitAlertsReadResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/audit-catalogs",
        method="get",
    ) == "#/components/schemas/AuditCatalogChangesResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/audit-installer-rates",
        method="get",
    ) == "#/components/schemas/AuditCatalogChangesResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/operations-center",
        method="get",
    ) == "#/components/schemas/OperationsCenterResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/operations-sla",
        method="get",
    ) == "#/components/schemas/OperationsSlaResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/operations-sla/history",
        method="get",
    ) == "#/components/schemas/OperationsSlaHistoryResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/issues-analytics",
        method="get",
    ) == "#/components/schemas/IssuesAnalyticsResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/reports/audit-issues",
        method="get",
    ) == "#/components/schemas/AuditCatalogChangesResponse"
    audit_catalog_export_schema = _response_schema(
        spec,
        path="/api/v1/admin/reports/audit-catalogs/export",
        method="get",
        content_type="text/csv",
    )
    assert audit_catalog_export_schema.get("type") == "string"
    audit_issues_export_schema = _response_schema(
        spec,
        path="/api/v1/admin/reports/audit-issues/export",
        method="get",
        content_type="text/csv",
    )
    assert audit_issues_export_schema.get("type") == "string"
    assert _response_ref(
        spec,
        path="/api/v1/admin/outbox",
        method="get",
    ) == "#/components/schemas/OutboxListResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/outbox/summary",
        method="get",
    ) == "#/components/schemas/OutboxSummaryResponse"
    assert _response_ref(
        spec,
        path="/api/v1/admin/outbox/{outbox_id}",
        method="get",
    ) == "#/components/schemas/OutboxItemDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/outbox/{outbox_id}/retry",
        method="post",
    ) == "#/components/schemas/OutboxRetryResponse"
    outbox_webhook_schema = _response_schema(
        spec,
        path="/api/v1/webhooks/outbox/status",
        method="post",
        content_type="text/plain",
    )
    assert outbox_webhook_schema.get("type") == "string"
    assert _response_ref(
        spec,
        path="/api/v1/admin/files/downloads",
        method="get",
    ) == "#/components/schemas/FileDownloadEventsResponse"
    assert _response_ref(
        spec,
        path="/api/v1/public/journals/{token}",
        method="get",
    ) == "#/components/schemas/PublicJournalGetResponse"
    assert _response_ref(
        spec,
        path="/api/v1/public/journals/{token}/sign",
        method="post",
    ) == "#/components/schemas/OkResponse"

    public_file_schema = _response_schema(
        spec,
        path="/api/v1/public/files/{token}",
        method="get",
        content_type="application/octet-stream",
    )
    assert public_file_schema.get("type") == "string"
    assert public_file_schema.get("format") == "binary"

    journal_pdf_schema = _response_schema(
        spec,
        path="/api/v1/admin/journals/{journal_id}/pdf",
        method="get",
        content_type="application/pdf",
    )
    assert journal_pdf_schema.get("type") == "string"
    assert journal_pdf_schema.get("format") == "binary"

    admin_installers_statuses = _response_statuses(
        spec,
        path="/api/v1/admin/installers",
        method="get",
    )
    assert "401" in admin_installers_statuses
    assert "403" in admin_installers_statuses
    assert "422" in admin_installers_statuses
    assert "400" in admin_installers_statuses
    assert "404" in admin_installers_statuses
    assert "409" in admin_installers_statuses
    assert _response_ref(
        spec,
        path="/api/v1/admin/installers",
        method="get",
        status="401",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installers",
        method="get",
        status="403",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/admin/installers",
        method="get",
        status="422",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert (
        _response_description(
            spec,
            path="/api/v1/admin/installers",
            method="get",
            status="401",
        )
        == "Unauthorized"
    )
    assert (
        _response_description(
            spec,
            path="/api/v1/admin/installers",
            method="get",
            status="403",
        )
        == "Forbidden"
    )

    installer_projects_statuses = _response_statuses(
        spec,
        path="/api/v1/installer/projects",
        method="get",
    )
    assert "401" in installer_projects_statuses
    assert "403" in installer_projects_statuses
    assert _response_ref(
        spec,
        path="/api/v1/installer/projects",
        method="get",
        status="401",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert _response_ref(
        spec,
        path="/api/v1/installer/projects",
        method="get",
        status="403",
    ) == "#/components/schemas/ApiErrorResponseDTO"

    assert "422" in _response_statuses(
        spec,
        path="/api/v1/auth/login",
        method="post",
    )
    assert _response_ref(
        spec,
        path="/api/v1/auth/login",
        method="post",
        status="422",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert "422" in _response_statuses(
        spec,
        path="/api/v1/admin/projects/{project_id}/doors/import",
        method="post",
    )
    assert "422" in _response_statuses(
        spec,
        path="/api/v1/admin/sync/reset/{installer_id}",
        method="post",
    )

    public_journal_statuses = _response_statuses(
        spec,
        path="/api/v1/public/journals/{token}",
        method="get",
    )
    assert _response_ref(
        spec,
        path="/api/v1/public/journals/{token}",
        method="get",
        status="422",
    ) == "#/components/schemas/ApiErrorResponseDTO"
    assert "401" not in public_journal_statuses
    assert "403" not in public_journal_statuses
