from __future__ import annotations

import uuid

from sqlalchemy import text

from app.core.config import settings
from app.modules.companies.application import alerts_service as alerts_module


def _cleanup_company(db_session, company_id: str) -> None:
    db_session.execute(
        text("DELETE FROM audit_logs WHERE company_id = :cid"),
        {"cid": company_id},
    )
    db_session.execute(
        text("DELETE FROM doors WHERE company_id = :cid"),
        {"cid": company_id},
    )
    db_session.execute(
        text("DELETE FROM projects WHERE company_id = :cid"),
        {"cid": company_id},
    )
    db_session.execute(
        text("DELETE FROM installer_rates WHERE company_id = :cid"),
        {"cid": company_id},
    )
    db_session.execute(
        text("DELETE FROM installers WHERE company_id = :cid"),
        {"cid": company_id},
    )
    db_session.execute(
        text("DELETE FROM reasons WHERE company_id = :cid"),
        {"cid": company_id},
    )
    db_session.execute(
        text("DELETE FROM door_types WHERE company_id = :cid"),
        {"cid": company_id},
    )
    db_session.execute(
        text("DELETE FROM company_plans WHERE company_id = :cid"),
        {"cid": company_id},
    )
    db_session.execute(
        text("DELETE FROM auth_refresh_tokens WHERE company_id = :cid"),
        {"cid": company_id},
    )
    db_session.execute(
        text("DELETE FROM users WHERE company_id = :cid"),
        {"cid": company_id},
    )
    db_session.execute(
        text("DELETE FROM companies WHERE id = :cid"),
        {"cid": company_id},
    )
    db_session.commit()


def _login_admin(client_raw, *, company_id: str, email: str, password: str) -> str:
    login_resp = client_raw.post(
        "/api/v1/auth/login",
        json={
            "company_id": company_id,
            "email": email,
            "password": password,
        },
    )
    assert login_resp.status_code == 200, login_resp.text
    return login_resp.json()["access_token"]


def test_platform_companies_require_valid_token(client_raw, monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_TOKEN", "platform-test-token")

    no_token = client_raw.get("/api/v1/platform/companies")
    assert no_token.status_code == 403, no_token.text
    assert no_token.json()["error"]["code"] == "FORBIDDEN"

    bad_token = client_raw.get(
        "/api/v1/platform/companies",
        headers={"X-Platform-Token": "wrong-token"},
    )
    assert bad_token.status_code == 403, bad_token.text
    assert bad_token.json()["error"]["code"] == "FORBIDDEN"


def test_platform_create_company_bootstraps_admin_and_can_login(
    client_raw, db_session, monkeypatch
):
    token = "platform-test-token"
    monkeypatch.setattr(settings, "PLATFORM_API_TOKEN", token)

    company_name = f"Platform Co {uuid.uuid4().hex[:8]}"
    admin_email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    admin_password = "PlatformPass123"

    create_resp = client_raw.post(
        "/api/v1/platform/companies",
        headers={"X-Platform-Token": token},
        json={
            "name": company_name,
            "admin_email": admin_email,
            "admin_password": admin_password,
            "admin_full_name": "Owner One",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    company_id = body["company"]["id"]

    try:
        assert body["company"]["name"] == company_name
        assert body["company"]["is_active"] is True
        assert body["admin_user_id"]

        door_types_count = db_session.execute(
            text("SELECT COUNT(*) FROM door_types WHERE company_id = :cid"),
            {"cid": company_id},
        ).scalar_one()
        reasons_count = db_session.execute(
            text("SELECT COUNT(*) FROM reasons WHERE company_id = :cid"),
            {"cid": company_id},
        ).scalar_one()
        plan_count = db_session.execute(
            text("SELECT COUNT(*) FROM company_plans WHERE company_id = :cid"),
            {"cid": company_id},
        ).scalar_one()
        assert int(door_types_count) == 6
        assert int(reasons_count) == 5
        assert int(plan_count) == 1

        login_resp = client_raw.post(
            "/api/v1/auth/login",
            json={
                "company_id": company_id,
                "email": admin_email,
                "password": admin_password,
            },
        )
        assert login_resp.status_code == 200, login_resp.text
        tokens = login_resp.json()
        assert tokens["access_token"]
        assert tokens["refresh_token"]
    finally:
        _cleanup_company(db_session, company_id)


def test_platform_company_plan_and_usage_endpoints(
    client_raw, db_session, monkeypatch
):
    token = "platform-test-token"
    monkeypatch.setattr(settings, "PLATFORM_API_TOKEN", token)

    create_resp = client_raw.post(
        "/api/v1/platform/companies",
        headers={"X-Platform-Token": token},
        json={
            "name": f"Plan Co {uuid.uuid4().hex[:8]}",
            "admin_email": f"owner-{uuid.uuid4().hex[:8]}@example.com",
            "admin_password": "PlatformPass123",
            "admin_full_name": "Owner Plan",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    company_id = create_resp.json()["company"]["id"]

    try:
        get_plan_resp = client_raw.get(
            f"/api/v1/platform/companies/{company_id}/plan",
            headers={"X-Platform-Token": token},
        )
        assert get_plan_resp.status_code == 200, get_plan_resp.text
        assert get_plan_resp.json()["plan_code"] == "trial"
        assert get_plan_resp.json()["max_projects"] == 120
        assert get_plan_resp.json()["max_admin_users"] == 10
        assert get_plan_resp.json()["max_installer_users"] == 15

        update_plan_resp = client_raw.put(
            f"/api/v1/platform/companies/{company_id}/plan",
            headers={"X-Platform-Token": token},
            json={
                "plan_code": "enterprise",
                "is_active": True,
                "max_users": 500,
                "max_admin_users": 100,
                "max_installer_users": 350,
                "max_installers": 300,
                "max_projects": 2000,
                "max_doors_per_project": 50000,
                "monthly_price": "2999.00",
                "currency": "usd",
                "notes": "Enterprise pilot",
            },
        )
        assert update_plan_resp.status_code == 200, update_plan_resp.text
        updated = update_plan_resp.json()
        assert updated["plan_code"] == "enterprise"
        assert updated["max_users"] == 500
        assert updated["max_admin_users"] == 100
        assert updated["max_installer_users"] == 350
        assert updated["currency"] == "USD"
        assert updated["monthly_price"] == "2999.00"

        usage_resp = client_raw.get(
            f"/api/v1/platform/companies/{company_id}/usage",
            headers={"X-Platform-Token": token},
        )
        assert usage_resp.status_code == 200, usage_resp.text
        usage = usage_resp.json()
        assert usage["active_users"] == 1
        assert usage["active_admin_users"] == 1
        assert usage["active_installer_users"] == 0
        assert usage["active_installers"] == 0
        assert usage["active_projects"] == 0
        assert usage["total_doors"] == 0
    finally:
        _cleanup_company(db_session, company_id)


def test_platform_update_company_status_and_include_inactive_listing(
    client_raw, db_session, monkeypatch
):
    token = "platform-test-token"
    monkeypatch.setattr(settings, "PLATFORM_API_TOKEN", token)

    create_resp = client_raw.post(
        "/api/v1/platform/companies",
        headers={"X-Platform-Token": token},
        json={
            "name": f"Inactive Co {uuid.uuid4().hex[:8]}",
            "admin_email": f"owner-{uuid.uuid4().hex[:8]}@example.com",
            "admin_password": "PlatformPass123",
            "admin_full_name": "Owner Two",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    company_id = create_resp.json()["company"]["id"]

    try:
        deactivate_resp = client_raw.patch(
            f"/api/v1/platform/companies/{company_id}/status",
            headers={"X-Platform-Token": token},
            json={"is_active": False},
        )
        assert deactivate_resp.status_code == 200, deactivate_resp.text
        assert deactivate_resp.json()["is_active"] is False

        active_only = client_raw.get(
            "/api/v1/platform/companies",
            headers={"X-Platform-Token": token},
        )
        assert active_only.status_code == 200, active_only.text
        active_ids = {item["id"] for item in active_only.json()["items"]}
        assert company_id not in active_ids

        with_inactive = client_raw.get(
            "/api/v1/platform/companies?include_inactive=true",
            headers={"X-Platform-Token": token},
        )
        assert with_inactive.status_code == 200, with_inactive.text
        by_id = {item["id"]: item for item in with_inactive.json()["items"]}
        assert company_id in by_id
        assert by_id[company_id]["is_active"] is False
    finally:
        _cleanup_company(db_session, company_id)


def test_plan_limits_soft_enforced_for_installers_projects_and_doors(
    client_raw, db_session, monkeypatch
):
    token = "platform-test-token"
    monkeypatch.setattr(settings, "PLATFORM_API_TOKEN", token)
    monkeypatch.setattr(settings, "PLAN_ALERT_WARN_PCT", 80)
    monkeypatch.setattr(settings, "PLAN_ALERT_DANGER_PCT", 95)
    monkeypatch.setattr(settings, "PLAN_ALERT_COOLDOWN_MINUTES", 360)
    monkeypatch.setattr(settings, "PLAN_ALERT_WEBHOOK_URL", "https://alerts.local/plan")
    webhook_calls: list[dict] = []

    def _fake_plan_alert_post(url, json, timeout):
        webhook_calls.append({"url": url, "json": json, "timeout": timeout})
        class _Resp:
            status_code = 200
        return _Resp()

    monkeypatch.setattr(alerts_module.httpx, "post", _fake_plan_alert_post)

    admin_email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    admin_password = "PlatformPass123"
    create_resp = client_raw.post(
        "/api/v1/platform/companies",
        headers={"X-Platform-Token": token},
        json={
            "name": f"Limited Co {uuid.uuid4().hex[:8]}",
            "admin_email": admin_email,
            "admin_password": admin_password,
            "admin_full_name": "Owner Limits",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    company_id = create_resp.json()["company"]["id"]

    try:
        update_plan_resp = client_raw.put(
            f"/api/v1/platform/companies/{company_id}/plan",
            headers={"X-Platform-Token": token},
            json={
                "plan_code": "tiny",
                "is_active": True,
                "max_users": 1,
                "max_installers": 1,
                "max_projects": 1,
                "max_doors_per_project": 2,
                "monthly_price": "99.00",
                "currency": "USD",
                "notes": "tiny plan for limits test",
            },
        )
        assert update_plan_resp.status_code == 200, update_plan_resp.text

        create_user_blocked = client_raw.post(
            f"/api/v1/platform/companies/{company_id}/users",
            headers={"X-Platform-Token": token},
            json={
                "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
                "full_name": "Second User",
                "password": "SecondUser123",
                "role": "INSTALLER",
                "is_active": True,
            },
        )
        assert create_user_blocked.status_code == 409, create_user_blocked.text
        assert create_user_blocked.json()["error"]["code"] == "CONFLICT"

        expand_plan_resp = client_raw.put(
            f"/api/v1/platform/companies/{company_id}/plan",
            headers={"X-Platform-Token": token},
            json={
                "plan_code": "tiny",
                "is_active": True,
                "max_users": 2,
                "max_installers": 1,
                "max_projects": 1,
                "max_doors_per_project": 2,
                "monthly_price": "99.00",
                "currency": "USD",
                "notes": "expanded for one extra user",
            },
        )
        assert expand_plan_resp.status_code == 200, expand_plan_resp.text

        create_user_ok = client_raw.post(
            f"/api/v1/platform/companies/{company_id}/users",
            headers={"X-Platform-Token": token},
            json={
                "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
                "full_name": "Second User",
                "password": "SecondUser123",
                "role": "INSTALLER",
                "is_active": True,
            },
        )
        assert create_user_ok.status_code == 201, create_user_ok.text
        assert create_user_ok.json()["role"] == "INSTALLER"

        access_token = _login_admin(
            client_raw,
            company_id=company_id,
            email=admin_email,
            password=admin_password,
        )
        auth = {"Authorization": f"Bearer {access_token}"}

        create_installer_1 = client_raw.post(
            "/api/v1/admin/installers",
            headers=auth,
            json={
                "full_name": "Installer One",
                "phone": "+10000111111",
                "status": "ACTIVE",
                "is_active": True,
            },
        )
        assert create_installer_1.status_code == 201, create_installer_1.text

        create_installer_2 = client_raw.post(
            "/api/v1/admin/installers",
            headers=auth,
            json={
                "full_name": "Installer Two",
                "phone": "+10000111112",
                "status": "ACTIVE",
                "is_active": True,
            },
        )
        assert create_installer_2.status_code == 409, create_installer_2.text
        assert create_installer_2.json()["error"]["code"] == "CONFLICT"

        create_project_1 = client_raw.post(
            "/api/v1/admin/projects",
            headers=auth,
            json={"name": "Limited Project A", "address": "Address A"},
        )
        assert create_project_1.status_code == 200, create_project_1.text
        project_id = create_project_1.json()["id"]

        create_project_2 = client_raw.post(
            "/api/v1/admin/projects",
            headers=auth,
            json={"name": "Limited Project B", "address": "Address B"},
        )
        assert create_project_2.status_code == 409, create_project_2.text
        assert create_project_2.json()["error"]["code"] == "CONFLICT"

        door_type_id = db_session.execute(
            text(
                "SELECT id FROM door_types "
                "WHERE company_id = :cid "
                "ORDER BY created_at ASC LIMIT 1"
            ),
            {"cid": company_id},
        ).scalar_one()

        import_2_doors = client_raw.post(
            f"/api/v1/admin/projects/{project_id}/doors/import",
            headers=auth,
            json={
                "rows": [
                    {
                        "door_type_id": str(door_type_id),
                        "unit_label": "A-01",
                        "our_price": "100.00",
                    },
                    {
                        "door_type_id": str(door_type_id),
                        "unit_label": "A-02",
                        "our_price": "100.00",
                    },
                ]
            },
        )
        assert import_2_doors.status_code == 200, import_2_doors.text
        assert import_2_doors.json()["imported"] == 2

        import_3rd_door = client_raw.post(
            f"/api/v1/admin/projects/{project_id}/doors/import",
            headers=auth,
            json={
                "rows": [
                    {
                        "door_type_id": str(door_type_id),
                        "unit_label": "A-03",
                        "our_price": "100.00",
                    }
                ]
            },
        )
        assert import_3rd_door.status_code == 409, import_3rd_door.text
        assert import_3rd_door.json()["error"]["code"] == "CONFLICT"

        limit_actions = db_session.execute(
            text(
                "SELECT action FROM audit_logs "
                "WHERE company_id = :cid AND action LIKE 'PLAN_LIMIT_BLOCK_%'"
            ),
            {"cid": company_id},
        ).scalars().all()
        assert {
            "PLAN_LIMIT_BLOCK_INSTALLER_CREATE",
            "PLAN_LIMIT_BLOCK_PROJECT_CREATE",
            "PLAN_LIMIT_BLOCK_DOOR_IMPORT",
        }.issubset(set(limit_actions))

        alert_actions = db_session.execute(
            text(
                "SELECT action FROM audit_logs "
                "WHERE company_id = :cid AND action LIKE 'PLAN_LIMIT_ALERT_%'"
            ),
            {"cid": company_id},
        ).scalars().all()
        assert {
            "PLAN_LIMIT_ALERT_DANGER_USERS",
            "PLAN_LIMIT_ALERT_DANGER_INSTALLERS",
            "PLAN_LIMIT_ALERT_DANGER_PROJECTS",
            "PLAN_LIMIT_ALERT_DANGER_DOORS_PER_PROJECT",
        }.issubset(set(alert_actions))
        assert len(webhook_calls) >= 4
        assert all(call["url"] == "https://alerts.local/plan" for call in webhook_calls)
        assert all(call["json"]["type"] == "PLAN_LIMIT_ALERT" for call in webhook_calls)
    finally:
        _cleanup_company(db_session, company_id)


def test_platform_role_aware_user_limits_enforced(
    client_raw,
    db_session,
    monkeypatch,
):
    token = "platform-test-token"
    monkeypatch.setattr(settings, "PLATFORM_API_TOKEN", token)

    admin_email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    admin_password = "PlatformPass123"
    create_resp = client_raw.post(
        "/api/v1/platform/companies",
        headers={"X-Platform-Token": token},
        json={
            "name": f"Role Limits Co {uuid.uuid4().hex[:8]}",
            "admin_email": admin_email,
            "admin_password": admin_password,
            "admin_full_name": "Owner Role Limits",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    company_id = create_resp.json()["company"]["id"]

    try:
        update_plan_resp = client_raw.put(
            f"/api/v1/platform/companies/{company_id}/plan",
            headers={"X-Platform-Token": token},
            json={
                "plan_code": "enterprise-lite",
                "is_active": True,
                "max_users": 3,
                "max_admin_users": 1,
                "max_installer_users": 2,
                "max_installers": 5,
                "max_projects": 10,
                "max_doors_per_project": 1000,
                "monthly_price": "199.00",
                "currency": "USD",
                "notes": "role-aware limits test",
            },
        )
        assert update_plan_resp.status_code == 200, update_plan_resp.text
        assert update_plan_resp.json()["max_admin_users"] == 1
        assert update_plan_resp.json()["max_installer_users"] == 2

        second_admin = client_raw.post(
            f"/api/v1/platform/companies/{company_id}/users",
            headers={"X-Platform-Token": token},
            json={
                "email": f"admin-{uuid.uuid4().hex[:8]}@example.com",
                "full_name": "Second Admin",
                "password": "SecondAdmin123",
                "role": "ADMIN",
                "is_active": True,
            },
        )
        assert second_admin.status_code == 409, second_admin.text
        assert second_admin.json()["error"]["code"] == "CONFLICT"

        installer_user_1 = client_raw.post(
            f"/api/v1/platform/companies/{company_id}/users",
            headers={"X-Platform-Token": token},
            json={
                "email": f"installer-{uuid.uuid4().hex[:8]}@example.com",
                "full_name": "Installer User 1",
                "password": "InstallerUser123",
                "role": "INSTALLER",
                "is_active": True,
            },
        )
        assert installer_user_1.status_code == 201, installer_user_1.text

        installer_user_2 = client_raw.post(
            f"/api/v1/platform/companies/{company_id}/users",
            headers={"X-Platform-Token": token},
            json={
                "email": f"installer-{uuid.uuid4().hex[:8]}@example.com",
                "full_name": "Installer User 2",
                "password": "InstallerUser123",
                "role": "INSTALLER",
                "is_active": True,
            },
        )
        assert installer_user_2.status_code == 201, installer_user_2.text

        installer_user_3 = client_raw.post(
            f"/api/v1/platform/companies/{company_id}/users",
            headers={"X-Platform-Token": token},
            json={
                "email": f"installer-{uuid.uuid4().hex[:8]}@example.com",
                "full_name": "Installer User 3",
                "password": "InstallerUser123",
                "role": "INSTALLER",
                "is_active": True,
            },
        )
        assert installer_user_3.status_code == 409, installer_user_3.text
        assert installer_user_3.json()["error"]["code"] == "CONFLICT"

        usage_resp = client_raw.get(
            f"/api/v1/platform/companies/{company_id}/usage",
            headers={"X-Platform-Token": token},
        )
        assert usage_resp.status_code == 200, usage_resp.text
        usage = usage_resp.json()
        assert usage["active_users"] == 3
        assert usage["active_admin_users"] == 1
        assert usage["active_installer_users"] == 2
    finally:
        _cleanup_company(db_session, company_id)
