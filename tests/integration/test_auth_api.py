from __future__ import annotations

import uuid

from app.api.v1 import rate_limit
from app.core.config import settings
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


def test_logout_refresh_revokes_token(client, company_id, make_user):
    password = "LogoutPass123"
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
    refresh_token = login_resp.json()["refresh_token"]

    logout_resp = client.post(
        "/api/v1/auth/logout-refresh",
        json={"refresh_token": refresh_token},
    )
    assert logout_resp.status_code == 200, logout_resp.text
    assert logout_resp.json()["ok"] is True
    assert logout_resp.json()["revoked"] is True

    refresh_again_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_again_resp.status_code == 403, refresh_again_resp.text
    assert refresh_again_resp.json()["error"]["code"] == "FORBIDDEN"


def test_logout_all_revokes_all_active_sessions(client, company_id, make_user):
    password = "LogoutAllPass123"
    user = make_user(role=UserRole.ADMIN, password=password)

    login_a = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
        },
    )
    login_b = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
        },
    )
    assert login_a.status_code == 200, login_a.text
    assert login_b.status_code == 200, login_b.text

    access_token = login_a.json()["access_token"]
    refresh_a = login_a.json()["refresh_token"]
    refresh_b = login_b.json()["refresh_token"]

    logout_all_resp = client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_all_resp.status_code == 200, logout_all_resp.text
    assert logout_all_resp.json()["ok"] is True
    assert logout_all_resp.json()["revoked_count"] >= 2

    refresh_a_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_a},
    )
    refresh_b_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_b},
    )
    assert refresh_a_resp.status_code == 403, refresh_a_resp.text
    assert refresh_b_resp.status_code == 403, refresh_b_resp.text


def test_login_rate_limit_returns_403(client_raw, monkeypatch):
    rate_limit._reset_rate_limits_for_tests()
    monkeypatch.setattr(settings, "AUTH_LOGIN_RL_WINDOW_SEC", 60)
    monkeypatch.setattr(settings, "AUTH_LOGIN_RL_MAX_REQ", 2)

    payload = {
        "company_id": str(uuid.uuid4()),
        "email": "nobody@example.com",
        "password": "secret123",
    }
    r1 = client_raw.post("/api/v1/auth/login", json=payload)
    r2 = client_raw.post("/api/v1/auth/login", json=payload)
    r3 = client_raw.post("/api/v1/auth/login", json=payload)

    assert r1.status_code in (403, 404), r1.text
    assert r2.status_code in (403, 404), r2.text
    assert r3.status_code == 403, r3.text
    assert r3.json()["error"]["message"] == "Too many requests. Slow down."

    rate_limit._reset_rate_limits_for_tests()


def test_refresh_rate_limit_returns_403(client_raw, monkeypatch):
    rate_limit._reset_rate_limits_for_tests()
    monkeypatch.setattr(settings, "AUTH_REFRESH_RL_WINDOW_SEC", 60)
    monkeypatch.setattr(settings, "AUTH_REFRESH_RL_MAX_REQ", 2)

    payload = {"refresh_token": "invalid-refresh-token"}
    r1 = client_raw.post("/api/v1/auth/refresh", json=payload)
    r2 = client_raw.post("/api/v1/auth/refresh", json=payload)
    r3 = client_raw.post("/api/v1/auth/refresh", json=payload)

    assert r1.status_code == 403, r1.text
    assert r2.status_code == 403, r2.text
    assert r3.status_code == 403, r3.text
    assert r3.json()["error"]["message"] == "Too many requests. Slow down."

    rate_limit._reset_rate_limits_for_tests()
