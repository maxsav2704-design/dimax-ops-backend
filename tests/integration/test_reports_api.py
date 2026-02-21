from __future__ import annotations

import uuid


def test_reports_kpi_returns_expected_shape(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/kpi")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "period_from",
        "period_to",
        "installed_doors",
        "not_installed_doors",
        "payroll_total",
        "revenue_total",
        "profit_total",
        "problem_projects",
        "missing_rates_installed_doors",
        "missing_addon_plans_done",
    ):
        assert key in body


def test_reports_dashboard_returns_expected_shape(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "kpi" in body
    assert "sync_health" in body
    assert isinstance(body["kpi"], dict)
    assert isinstance(body["sync_health"], dict)


def test_reports_problem_projects_returns_list_payload(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/problem-projects")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_reports_top_reasons_returns_list_payload(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/top-reasons")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_reports_delivery_returns_expected_shape(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/delivery")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "period_from",
        "period_to",
        "whatsapp_pending",
        "whatsapp_delivered",
        "whatsapp_failed",
        "email_sent",
        "email_failed",
    ):
        assert key in body


def test_reports_project_profit_not_found_returns_404(client_admin_real_uow):
    resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/project-profit/{uuid.uuid4()}"
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_reports_project_profit_existing_project_returns_payload(
    client_admin_real_uow,
):
    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects",
        json={
            "name": "Reports Project",
            "address": "Reports Street 1",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    project_id = create_resp.json()["id"]

    profit_resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/project-profit/{project_id}"
    )
    assert profit_resp.status_code == 200, profit_resp.text
    body = profit_resp.json()
    assert body["project_id"] == project_id
    for key in (
        "installed_doors",
        "payroll_total",
        "revenue_total",
        "profit_total",
        "missing_rates_installed_doors",
    ):
        assert key in body


def test_reports_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/reports/kpi")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"
