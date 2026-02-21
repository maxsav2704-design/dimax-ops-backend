from __future__ import annotations

from app.modules.identity.domain.enums import UserRole


def test_admin_endpoint_without_token_is_rejected(client_raw):
    resp = client_raw.get("/api/v1/admin/installers")
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_admin_endpoint_with_invalid_token_is_rejected(client_raw):
    resp = client_raw.get(
        "/api/v1/admin/installers",
        headers={"Authorization": "Bearer definitely-invalid-token"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_admin_endpoint_with_refresh_token_is_rejected(
    client_raw, company_id, make_user
):
    password = "AccessOnly123"
    user = make_user(role=UserRole.ADMIN, password=password)

    login_resp = client_raw.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
        },
    )
    assert login_resp.status_code == 200, login_resp.text
    refresh_token = login_resp.json()["refresh_token"]

    resp = client_raw.get(
        "/api/v1/admin/installers",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"
