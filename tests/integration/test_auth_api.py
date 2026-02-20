from __future__ import annotations

from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.refresh_tokens_models import RefreshTokenORM


def test_login_success_returns_token_pair(client, company_id, make_user):
    password = "StrongPass123"
    user = make_user(role=UserRole.ADMIN, password=password)

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert isinstance(body["refresh_token"], str) and body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_login_invalid_password_returns_403(client, company_id, make_user):
    user = make_user(role=UserRole.ADMIN, password="CorrectPass123")

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": "wrong-password",
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_login_inactive_user_returns_404(client, company_id, make_user):
    user = make_user(role=UserRole.ADMIN, password="Secret123", is_active=False)

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": "Secret123",
        },
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_refresh_rotates_token_and_revokes_old(client, db_session, company_id, make_user):
    password = "RotatePass123"
    user = make_user(role=UserRole.ADMIN, password=password)

    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
        },
    )
    assert login_resp.status_code == 200, login_resp.text
    original = login_resp.json()

    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original["refresh_token"]},
    )
    assert refresh_resp.status_code == 200, refresh_resp.text
    rotated = refresh_resp.json()
    assert rotated["refresh_token"] != original["refresh_token"]

    old_refresh_again_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original["refresh_token"]},
    )
    assert old_refresh_again_resp.status_code == 403, old_refresh_again_resp.text
    assert old_refresh_again_resp.json()["error"]["code"] == "FORBIDDEN"

    rows = (
        db_session.query(RefreshTokenORM)
        .filter(
            RefreshTokenORM.company_id == company_id,
            RefreshTokenORM.user_id == user.id,
        )
        .all()
    )
    assert len(rows) == 2
    assert sum(1 for r in rows if r.revoked_at is not None) == 1
    assert sum(1 for r in rows if r.revoked_at is None) == 1
