from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.identity.domain.enums import UserRole
from app.modules.installers.infrastructure.models import InstallerORM


def _auth(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _login(client_raw, *, company_id: str, email: str, password: str) -> str:
    resp = client_raw.post(
        "/api/v1/auth/login",
        json={
            "company_id": company_id,
            "email": email,
            "password": password,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture()
def rbac_tokens(client_raw, db_session, company_id, make_user):
    admin_password = "RbacAdmin123"
    installer_password = "RbacInstaller123"

    admin_user = make_user(role=UserRole.ADMIN, password=admin_password)
    installer_user = make_user(
        role=UserRole.INSTALLER, password=installer_password
    )
    db_session.add(
        InstallerORM(
            company_id=company_id,
            full_name="RBAC Installer Profile",
            phone=f"+1222{uuid.uuid4().hex[:8]}",
            email=None,
            address=None,
            passport_id=None,
            notes=None,
            status="ACTIVE",
            is_active=True,
            user_id=installer_user.id,
        )
    )
    db_session.commit()

    return {
        "admin": _login(
            client_raw,
            company_id=str(company_id),
            email=admin_user.email,
            password=admin_password,
        ),
        "installer": _login(
            client_raw,
            company_id=str(company_id),
            email=installer_user.email,
            password=installer_password,
        ),
    }


def test_rbac_matrix_admin_endpoints(client_raw, rbac_tokens):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    starts = now.isoformat().replace("+00:00", "Z")
    ends = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    cases = [
        ("GET", "/api/v1/admin/installers", None, 200),
        ("GET", "/api/v1/admin/installer-rates", None, 200),
        (
            "GET",
            f"/api/v1/admin/installer-rates/timeline?installer_id={uuid.uuid4()}&door_type_id={uuid.uuid4()}",
            None,
            200,
        ),
        (
            "POST",
            "/api/v1/admin/installer-rates/bulk",
            {
                "ids": [str(uuid.uuid4())],
                "operation": "set_price",
                "price": "100.00",
            },
            200,
        ),
        ("GET", "/api/v1/admin/projects", None, 200),
        ("GET", "/api/v1/admin/projects/import-runs/failed-queue", None, 200),
        ("GET", "/api/v1/admin/journals", None, 200),
        ("GET", "/api/v1/admin/settings/communication-templates", None, 200),
        ("GET", "/api/v1/admin/settings/integrations/health", None, 200),
        ("GET", "/api/v1/admin/dashboard", None, 200),
        ("GET", "/api/v1/admin/reports/dashboard", None, 200),
        ("GET", "/api/v1/admin/reports/dispatcher-board", None, 200),
        ("GET", "/api/v1/admin/reports/installers-kpi", None, 200),
        ("GET", "/api/v1/admin/reports/installers-profitability-matrix", None, 200),
        ("GET", "/api/v1/admin/reports/installer-project-profitability", None, 200),
        ("GET", f"/api/v1/admin/reports/installers-kpi/{uuid.uuid4()}", None, 404),
        ("GET", "/api/v1/admin/reports/installers-kpi/export", None, 200),
        ("GET", "/api/v1/admin/reports/order-numbers-kpi", None, 200),
        ("GET", "/api/v1/admin/reports/order-numbers-kpi/export", None, 200),
        ("GET", f"/api/v1/admin/reports/project-plan-fact/{uuid.uuid4()}", None, 404),
        ("GET", f"/api/v1/admin/reports/project-risk-drilldown/{uuid.uuid4()}", None, 404),
        ("GET", "/api/v1/admin/reports/projects-margin", None, 200),
        ("GET", "/api/v1/admin/reports/issues-addons-impact", None, 200),
        ("GET", "/api/v1/admin/reports/risk-concentration", None, 200),
        ("GET", "/api/v1/admin/reports/executive/export", None, 200),
        ("GET", "/api/v1/admin/reports/operations-center", None, 200),
        ("GET", "/api/v1/admin/reports/operations-sla", None, 200),
        ("GET", "/api/v1/admin/reports/operations-sla/history", None, 200),
        ("GET", "/api/v1/admin/reports/issues-analytics", None, 200),
        ("GET", "/api/v1/admin/reports/audit-issues", None, 200),
        ("GET", "/api/v1/admin/reports/audit-issues/export", None, 200),
        ("GET", "/api/v1/admin/reports/audit-catalogs/export", None, 200),
        ("GET", "/api/v1/admin/reports/audit-installer-rates", None, 200),
        ("GET", "/api/v1/admin/reports/audit-installer-rates/export", None, 200),
        (
            "POST",
            "/api/v1/admin/projects/import-runs/reconcile-latest",
            {"project_ids": [str(uuid.uuid4())]},
            200,
        ),
        (
            "POST",
            "/api/v1/admin/projects/import-runs/retry-failed",
            {"run_ids": [str(uuid.uuid4())]},
            200,
        ),
        ("GET", "/api/v1/admin/issues", None, 200),
        (
            "PATCH",
            "/api/v1/admin/issues/workflow/bulk",
            {"issue_ids": [str(uuid.uuid4())], "workflow_state": "TRIAGED"},
            200,
        ),
        ("GET", "/api/v1/admin/projects/import-mapping-profiles", None, 200),
        ("GET", "/api/v1/admin/outbox", None, 200),
        ("GET", "/api/v1/admin/outbox/summary", None, 200),
        ("GET", "/api/v1/admin/addons/types", None, 200),
        ("GET", f"/api/v1/admin/calendar/events?starts_at={starts}&ends_at={ends}", None, 200),
        ("GET", "/api/v1/admin/sync/health/summary", None, 200),
    ]

    for method, path, payload, admin_expected_status in cases:
        anon = client_raw.request(method, path, json=payload)
        assert anon.status_code == 401, f"{path} anonymous: {anon.text}"

        installer = client_raw.request(
            method,
            path,
            json=payload,
            headers=_auth(rbac_tokens["installer"]),
        )
        assert installer.status_code == 403, f"{path} installer: {installer.text}"

        admin = client_raw.request(
            method,
            path,
            json=payload,
            headers=_auth(rbac_tokens["admin"]),
        )
        assert admin.status_code == admin_expected_status, f"{path} admin: {admin.text}"


def test_rbac_matrix_installer_endpoints(client_raw, rbac_tokens):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    starts = now.isoformat().replace("+00:00", "Z")
    ends = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    cases = [
        ("GET", "/api/v1/installer/projects", None),
        ("GET", f"/api/v1/installer/calendar/events?starts_at={starts}&ends_at={ends}", None),
        (
            "POST",
            "/api/v1/installer/sync",
            {
                "since_cursor": 0,
                "ack_cursor": 0,
                "events": [],
                "app_version": "rbac-test",
                "device_id": "rbac-device",
            },
        ),
    ]

    for method, path, payload in cases:
        anon = client_raw.request(method, path, json=payload)
        assert anon.status_code == 401, f"{path} anonymous: {anon.text}"

        installer = client_raw.request(
            method,
            path,
            json=payload,
            headers=_auth(rbac_tokens["installer"]),
        )
        assert installer.status_code == 200, f"{path} installer: {installer.text}"

        admin = client_raw.request(
            method,
            path,
            json=payload,
            headers=_auth(rbac_tokens["admin"]),
        )
        assert admin.status_code == 403, f"{path} admin: {admin.text}"
