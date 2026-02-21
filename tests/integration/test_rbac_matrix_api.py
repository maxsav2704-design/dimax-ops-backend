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
        ("GET", "/api/v1/admin/installers", None),
        ("GET", "/api/v1/admin/installer-rates", None),
        ("GET", "/api/v1/admin/projects", None),
        ("GET", "/api/v1/admin/journals", None),
        ("GET", "/api/v1/admin/dashboard", None),
        ("GET", "/api/v1/admin/reports/dashboard", None),
        ("GET", "/api/v1/admin/addons/types", None),
        ("GET", f"/api/v1/admin/calendar/events?starts_at={starts}&ends_at={ends}", None),
        ("GET", "/api/v1/admin/sync/health/summary", None),
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
        assert installer.status_code == 403, f"{path} installer: {installer.text}"

        admin = client_raw.request(
            method,
            path,
            json=payload,
            headers=_auth(rbac_tokens["admin"]),
        )
        assert admin.status_code == 200, f"{path} admin: {admin.text}"


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
