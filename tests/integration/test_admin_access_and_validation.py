from __future__ import annotations

import uuid

from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import AdminProfileORM


def _login(client_raw, *, company_id: str, email: str, password: str) -> str:
    resp = client_raw.post(
        "/api/v1/auth/login",
        json={
            "company_id": company_id,
            "email": email,
            "password": password,
            "device_id": f"admin-access-{email}",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_admin_installers_list_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/installers")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_admin_installer_rates_list_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/installer-rates")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_admin_installer_rates_bulk_forbidden_for_installer_role(client_installer):
    resp = client_installer.post(
        "/api/v1/admin/installer-rates/bulk",
        json={
            "ids": [str(uuid.uuid4())],
            "operation": "set_price",
            "price": "100.00",
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_admin_installer_rates_timeline_forbidden_for_installer_role(client_installer):
    resp = client_installer.get(
        f"/api/v1/admin/installer-rates/timeline?installer_id={uuid.uuid4()}&door_type_id={uuid.uuid4()}"
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_admin_installers_link_forbidden_for_installer_role(client_installer):
    resp = client_installer.post(
        f"/api/v1/admin/installers/{uuid.uuid4()}/link-user",
        json={"user_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_create_installer_validation_missing_required_field_returns_422(client):
    resp = client.post(
        "/api/v1/admin/installers",
        json={
            "phone": "+10000009999",
            "status": "ACTIVE",
            "is_active": True,
        },
    )
    assert resp.status_code == 422, resp.text


def test_create_installer_validation_field_boundaries_return_422(client):
    too_short_name = {
        "full_name": "A",
        "phone": "+10000009998",
        "status": "ACTIVE",
        "is_active": True,
    }
    short_resp = client.post("/api/v1/admin/installers", json=too_short_name)
    assert short_resp.status_code == 422, short_resp.text

    too_long_phone = {
        "full_name": "Valid Installer Name",
        "phone": "1" * 41,
        "status": "ACTIVE",
        "is_active": True,
    }
    long_resp = client.post("/api/v1/admin/installers", json=too_long_phone)
    assert long_resp.status_code == 422, long_resp.text


def test_create_installer_rate_validation_returns_422(client):
    missing_field_resp = client.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(uuid.uuid4()),
            "price": "100.00",
        },
    )
    assert missing_field_resp.status_code == 422, missing_field_resp.text

    negative_price_resp = client.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(uuid.uuid4()),
            "door_type_id": str(uuid.uuid4()),
            "price": "-1.00",
        },
    )
    assert negative_price_resp.status_code == 422, negative_price_resp.text

    naive_effective_from_resp = client.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(uuid.uuid4()),
            "door_type_id": str(uuid.uuid4()),
            "price": "10.00",
            "effective_from": "2026-01-01T00:00:00",
        },
    )
    assert naive_effective_from_resp.status_code == 422, naive_effective_from_resp.text


def test_update_installer_rate_validation_returns_422(client):
    resp = client.patch(
        f"/api/v1/admin/installer-rates/{uuid.uuid4()}",
        json={"price": "-5.00"},
    )
    assert resp.status_code == 422, resp.text


def test_bulk_installer_rate_validation_returns_422(client):
    missing_price_resp = client.post(
        "/api/v1/admin/installer-rates/bulk",
        json={
            "ids": [str(uuid.uuid4())],
            "operation": "set_price",
        },
    )
    assert missing_price_resp.status_code == 422, missing_price_resp.text

    invalid_operation_resp = client.post(
        "/api/v1/admin/installer-rates/bulk",
        json={
            "ids": [str(uuid.uuid4())],
            "operation": "activate",
            "price": "100.00",
        },
    )
    assert invalid_operation_resp.status_code == 422, invalid_operation_resp.text

    naive_effective_from_resp = client.post(
        "/api/v1/admin/installer-rates/bulk",
        json={
            "ids": [str(uuid.uuid4())],
            "operation": "set_price",
            "price": "100.00",
            "effective_from": "2026-03-01T00:00:00",
        },
    )
    assert naive_effective_from_resp.status_code == 422, naive_effective_from_resp.text

    delete_with_effective_from_resp = client.post(
        "/api/v1/admin/installer-rates/bulk",
        json={
            "ids": [str(uuid.uuid4())],
            "operation": "delete",
            "effective_from": "2026-03-01T00:00:00Z",
        },
    )
    assert delete_with_effective_from_resp.status_code == 422, delete_with_effective_from_resp.text


def test_timeline_installer_rate_validation_returns_422(client):
    resp = client.get(
        f"/api/v1/admin/installer-rates/timeline?installer_id={uuid.uuid4()}&door_type_id={uuid.uuid4()}&as_of=2026-03-01T00:00:00"
    )
    assert resp.status_code == 422, resp.text


def test_admin_rates_require_view_rates_capability(
    client_raw, db_session, company_id, make_user
):
    password = "RatesCap123"
    user = make_user(role=UserRole.ADMIN, password=password, with_admin_profile=False)
    db_session.add(
        AdminProfileORM(
            company_id=company_id,
            user_id=user.id,
            admin_scope="OPERATIONS",
            can_view_rates=False,
            can_manage_imports=True,
            can_manage_users=True,
        )
    )
    db_session.commit()

    token = _login(
        client_raw,
        company_id=str(company_id),
        email=user.email,
        password=password,
    )
    resp = client_raw.get(
        "/api/v1/admin/installer-rates",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_admin_financial_reports_require_view_rates_capability(
    client_raw, db_session, company_id, make_user
):
    password = "ReportsNoRates123"
    user = make_user(role=UserRole.ADMIN, password=password, with_admin_profile=False)
    db_session.add(
        AdminProfileORM(
            company_id=company_id,
            user_id=user.id,
            admin_scope="OPERATIONS",
            can_view_rates=False,
            can_manage_imports=True,
            can_manage_users=True,
        )
    )
    db_session.commit()

    token = _login(
        client_raw,
        company_id=str(company_id),
        email=user.email,
        password=password,
    )
    headers = {"Authorization": f"Bearer {token}"}

    financial_paths = [
        "/api/v1/admin/addons/types",
        f"/api/v1/admin/projects/{uuid.uuid4()}/addons",
        f"/api/v1/admin/projects/{uuid.uuid4()}/addons/plan",
        f"/api/v1/admin/projects/{uuid.uuid4()}/urgency-surcharges",
        "/api/v1/admin/reports/dashboard",
        "/api/v1/admin/reports/kpi",
        "/api/v1/admin/reports/installers-kpi",
        "/api/v1/admin/reports/installers-kpi/export",
        "/api/v1/admin/reports/order-numbers-kpi",
        "/api/v1/admin/reports/order-numbers-kpi/export",
        f"/api/v1/admin/reports/project-profit/{uuid.uuid4()}",
        f"/api/v1/admin/reports/project-plan-fact/{uuid.uuid4()}",
        f"/api/v1/admin/reports/project-risk-drilldown/{uuid.uuid4()}",
        "/api/v1/admin/reports/projects-margin",
        "/api/v1/admin/reports/issues-addons-impact",
        "/api/v1/admin/reports/risk-concentration",
        "/api/v1/admin/reports/executive/export",
        "/api/v1/admin/reports/audit-installer-rates",
        "/api/v1/admin/reports/audit-installer-rates/export",
        "/api/v1/admin/earnings/ledger",
        "/api/v1/admin/earnings/ledger/export",
    ]

    for path in financial_paths:
        resp = client_raw.get(path, headers=headers)
        assert resp.status_code == 403, f"{path}: {resp.text}"
        assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    mutation_cases = [
        (
            "POST",
            "/api/v1/admin/addons/types",
            {
                "name": "No Rates Addon",
                "unit": "pcs",
                "default_client_price": "10.00",
                "default_installer_price": "4.00",
            },
        ),
        (
            "PUT",
            f"/api/v1/admin/addons/projects/{uuid.uuid4()}/plan",
            {
                "addon_type_id": str(uuid.uuid4()),
                "qty_planned": "1.00",
                "client_price": "10.00",
                "installer_price": "4.00",
            },
        ),
        (
            "PUT",
            f"/api/v1/admin/projects/{uuid.uuid4()}/addons/plan",
            {
                "items": [
                    {
                        "addon_type_id": str(uuid.uuid4()),
                        "qty_planned": "1.00",
                        "client_price": "10.00",
                        "installer_price": "4.00",
                    }
                ]
            },
        ),
        (
            "POST",
            f"/api/v1/admin/projects/{uuid.uuid4()}/addons/plan",
            {
                "addon_type_id": str(uuid.uuid4()),
                "qty_planned": "1.00",
                "client_price": "10.00",
                "installer_price": "4.00",
                "notes": "restricted",
            },
        ),
        (
            "DELETE",
            f"/api/v1/admin/projects/{uuid.uuid4()}/addons/plan/{uuid.uuid4()}",
            None,
        ),
        (
            "POST",
            f"/api/v1/admin/projects/{uuid.uuid4()}/urgency-surcharges",
            {
                "scope": "PROJECT",
                "reason": "Rush approval",
                "client_amount": "100.00",
                "installer_amount": "40.00",
                "effective_date": None,
                "notes": "restricted",
            },
        ),
    ]

    for method, path, payload in mutation_cases:
        resp = client_raw.request(method, path, headers=headers, json=payload)
        assert resp.status_code == 403, f"{method} {path}: {resp.text}"
        assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_admin_project_imports_require_manage_imports_capability(
    client_raw, db_session, company_id, make_user
):
    password = "ImportsCap123"
    user = make_user(role=UserRole.ADMIN, password=password, with_admin_profile=False)
    db_session.add(
        AdminProfileORM(
            company_id=company_id,
            user_id=user.id,
            admin_scope="OPERATIONS",
            can_view_rates=True,
            can_manage_imports=False,
            can_manage_users=True,
        )
    )
    db_session.commit()

    token = _login(
        client_raw,
        company_id=str(company_id),
        email=user.email,
        password=password,
    )
    resp = client_raw.get(
        "/api/v1/admin/projects/import-mapping-profiles",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_admin_installers_are_readable_but_mutations_require_manage_users(
    client_raw, db_session, company_id, make_user
):
    password = "UsersCap123"
    user = make_user(role=UserRole.ADMIN, password=password, with_admin_profile=False)
    db_session.add(
        AdminProfileORM(
            company_id=company_id,
            user_id=user.id,
            admin_scope="OPERATIONS",
            can_view_rates=True,
            can_manage_imports=True,
            can_manage_users=False,
        )
    )
    db_session.commit()

    token = _login(
        client_raw,
        company_id=str(company_id),
        email=user.email,
        password=password,
    )
    headers = {"Authorization": f"Bearer {token}"}

    read_response = client_raw.get("/api/v1/admin/installers", headers=headers)
    assert read_response.status_code == 200, read_response.text

    write_response = client_raw.post(
        "/api/v1/admin/installers",
        headers=headers,
        json={"full_name": "Read Only Installer"},
    )
    assert write_response.status_code == 403, write_response.text
    assert write_response.json()["error"]["code"] == "FORBIDDEN_SCOPE"

def test_access_token_is_rejected_after_user_deactivation(
    client_raw,
    db_session,
    company_id,
    make_user,
):
    password = "DeactivateAccess123"
    user = make_user(role=UserRole.ADMIN, password=password)
    token = _login(
        client_raw,
        company_id=str(company_id),
        email=user.email,
        password=password,
    )

    user.is_active = False
    db_session.add(user)
    db_session.commit()

    response = client_raw.get(
        "/api/v1/admin/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_admin_without_profile_is_fail_closed(
    client_raw,
    company_id,
    make_user,
):
    password = "MissingProfile123"
    user = make_user(
        role=UserRole.ADMIN,
        password=password,
        with_admin_profile=False,
    )
    token = _login(
        client_raw,
        company_id=str(company_id),
        email=user.email,
        password=password,
    )

    response = client_raw.get(
        "/api/v1/admin/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_finance_and_viewer_scopes_cannot_mutate_admin_resources(
    client_raw,
    db_session,
    company_id,
    make_user,
):
    for scope in ("FINANCE", "VIEWER"):
        password = f"{scope.title()}Readonly123"
        user = make_user(
            role=UserRole.ADMIN,
            password=password,
            with_admin_profile=False,
        )
        db_session.add(
            AdminProfileORM(
                company_id=company_id,
                user_id=user.id,
                admin_scope=scope,
                can_view_rates=scope == "FINANCE",
                can_manage_imports=False,
                can_manage_users=False,
            )
        )
        db_session.commit()
        token = _login(
            client_raw,
            company_id=str(company_id),
            email=user.email,
            password=password,
        )

        response = client_raw.post(
            "/api/v1/admin/projects",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": f"Forbidden {scope} project",
                "address": "Read-only scope address",
            },
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FORBIDDEN_SCOPE"

def test_admin_read_scope_matrix_is_enforced(
    client_raw,
    db_session,
    company_id,
    make_user,
):
    scope_cases = (
        (
            "OPERATIONS",
            False,
            (
                ("/api/v1/admin/projects", 200),
                ("/api/v1/admin/settings/company", 403),
            ),
        ),
        (
            "FINANCE",
            True,
            (
                ("/api/v1/admin/reports/limits", 200),
                ("/api/v1/admin/issues", 403),
            ),
        ),
        (
            "VIEWER",
            False,
            (
                ("/api/v1/admin/projects", 200),
                ("/api/v1/admin/reports/limits", 403),
            ),
        ),
    )

    for index, (scope, can_view_rates, requests) in enumerate(scope_cases):
        password = f"ScopeRead{index}Valid123"
        user = make_user(
            role=UserRole.ADMIN,
            password=password,
            with_admin_profile=False,
        )
        db_session.add(
            AdminProfileORM(
                company_id=company_id,
                user_id=user.id,
                admin_scope=scope,
                can_view_rates=can_view_rates,
                can_manage_imports=False,
                can_manage_users=False,
            )
        )
        db_session.commit()
        token = _login(
            client_raw,
            company_id=str(company_id),
            email=user.email,
            password=password,
        )
        headers = {"Authorization": f"Bearer {token}"}

        for path, expected_status in requests:
            response = client_raw.get(path, headers=headers)
            assert response.status_code == expected_status, (
                f"{scope} GET {path}: {response.text}"
            )
            if expected_status == 403:
                assert response.json()["error"]["code"] == "FORBIDDEN_SCOPE"
