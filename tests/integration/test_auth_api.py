from __future__ import annotations

import base64
import bcrypt
import hashlib
import json
import uuid
from datetime import datetime, timezone

import pytest

from app.api.v1 import rate_limit
from app.core.config import settings
from app.core.security.jwt import create_refresh_token
from app.core.security.refresh_token_hash import hash_refresh_token
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM
from app.modules.identity.infrastructure.refresh_tokens_models import RefreshTokenORM


@pytest.fixture(autouse=True)
def reset_auth_rate_limits():
    rate_limit._reset_rate_limits_for_tests()
    yield
    rate_limit._reset_rate_limits_for_tests()


def test_login_success_returns_token_pair(client, db_session, company_id, make_user):
    password = "StrongPass123"  # gitleaks:allow - deterministic test credential
    user = make_user(
        role=UserRole.ADMIN,
        password=password,
        with_admin_profile=False,
    )

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
            "device_id": "pixel-auth-device",
        },
        headers={"User-Agent": "DimaxAuthTests/1.0"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert isinstance(body["refresh_token"], str) and body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["id"] == str(user.id)
    assert body["user"]["role"] == "ADMIN"
    assert body["user"]["language"] == "en"
    assert body["user"]["display_name"] == user.full_name
    assert body["user"]["admin_scope"] is None
    assert body["user"]["can_view_rates"] is False
    assert body["user"]["can_manage_imports"] is False
    assert body["user"]["can_manage_users"] is False

    row = (
        db_session.query(RefreshTokenORM)
        .filter(
            RefreshTokenORM.company_id == company_id,
            RefreshTokenORM.user_id == user.id,
        )
        .order_by(RefreshTokenORM.created_at.desc())
        .first()
    )
    assert row is not None
    assert row.token_hash == hash_refresh_token(body["refresh_token"])
    assert row.device_id == "pixel-auth-device"
    assert row.issued_at is not None
    assert row.last_used_at is not None
    assert row.ip_address == "testclient"
    assert row.user_agent == "DimaxAuthTests/1.0"


def test_access_token_ttl_is_15_minutes(client, company_id, make_user):
    password = "TokenTtl123"
    user = make_user(
        role=UserRole.ADMIN,
        password=password,
        with_admin_profile=False,
    )

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
            "device_id": "ttl-device",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()).decode())
    assert payload["exp"] - payload["iat"] == 900


def test_auth_me_returns_current_user_profile(client, company_id, make_user):
    password = "MePass123"
    user = make_user(role=UserRole.INSTALLER, password=password)

    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
            "device_id": "me-device",
        },
    )
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["access_token"]

    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200, me_resp.text
    body = me_resp.json()
    assert body["id"] == str(user.id)
    assert body["company_id"] == str(company_id)
    assert body["email"] == user.email
    assert body["full_name"] == user.full_name
    assert body["display_name"] == user.full_name
    assert body["language"] == "en"
    assert body["role"] == "INSTALLER"
    assert body["is_active"] is True
    assert body["admin_scope"] is None
    assert body["can_view_rates"] is None
    assert body["can_manage_imports"] is None
    assert body["can_manage_users"] is None


def test_admin_auth_payload_includes_scope_and_capabilities(
    client, db_session, company_id, make_user
):
    password = "AdminScope123"
    user = make_user(
        role=UserRole.ADMIN,
        password=password,
        with_admin_profile=False,
    )
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

    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
            "device_id": "admin-scope-device",
        },
    )
    assert login_resp.status_code == 200, login_resp.text
    login_body = login_resp.json()
    assert login_body["user"]["admin_scope"] == "OPERATIONS"
    assert login_body["user"]["can_view_rates"] is True
    assert login_body["user"]["can_manage_imports"] is True
    assert login_body["user"]["can_manage_users"] is False

    me_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_body['access_token']}"},
    )
    assert me_resp.status_code == 200, me_resp.text
    me_body = me_resp.json()
    assert me_body["admin_scope"] == "OPERATIONS"
    assert me_body["can_view_rates"] is True
    assert me_body["can_manage_imports"] is True
    assert me_body["can_manage_users"] is False


def test_login_invalid_password_returns_401(client, company_id, make_user):
    user = make_user(
        role=UserRole.ADMIN,
        password="CorrectPass123",  # gitleaks:allow - deterministic test credential
    )

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": "wrong-password",
            "device_id": "bad-password-device",
        },
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_requires_device_id(client, company_id, make_user):
    user = make_user(role=UserRole.ADMIN, password="NeedsDevice123")

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": "NeedsDevice123",
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert resp.json()["error"]["field"] == "device_id"


def test_login_inactive_user_returns_generic_401(client, company_id, make_user):
    user = make_user(role=UserRole.ADMIN, password="Secret123", is_active=False)

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": "Secret123",
            "device_id": "inactive-user-device",
        },
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_inactive_company_blocks_login_access_and_refresh(
    client,
    db_session,
    company_id,
    make_user,
):
    password = "InactiveCompany123"
    user = make_user(role=UserRole.ADMIN, password=password)
    login_payload = {
        "company_id": str(company_id),
        "email": user.email,
        "password": password,
        "device_id": "inactive-company-device",
    }

    login_resp = client.post("/api/v1/auth/login", json=login_payload)
    assert login_resp.status_code == 200, login_resp.text
    tokens = login_resp.json()

    company = db_session.query(CompanyORM).filter(CompanyORM.id == company_id).one()
    company.is_active = False
    db_session.commit()

    blocked_login = client.post("/api/v1/auth/login", json=login_payload)
    assert blocked_login.status_code == 401, blocked_login.text
    assert blocked_login.json()["error"]["code"] == "INVALID_CREDENTIALS"

    blocked_access = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert blocked_access.status_code == 403, blocked_access.text
    assert blocked_access.json()["error"]["code"] == "FORBIDDEN"

    blocked_refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert blocked_refresh.status_code == 401, blocked_refresh.text
    assert blocked_refresh.json()["error"]["code"] == "UNAUTHORIZED"


def test_refresh_rotates_token_and_revokes_old(client, db_session, company_id, make_user):
    password = "RotatePass123"
    user = make_user(role=UserRole.ADMIN, password=password)

    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
            "device_id": "rotate-device-a",
        },
        headers={"User-Agent": "DimaxRotate/1.0"},
    )
    assert login_resp.status_code == 200, login_resp.text
    original = login_resp.json()

    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": original["refresh_token"],
            "device_id": "rotate-device-a",
        },
        headers={"User-Agent": "DimaxRotate/2.0"},
    )
    assert refresh_resp.status_code == 200, refresh_resp.text
    rotated = refresh_resp.json()
    assert rotated["refresh_token"] != original["refresh_token"]
    assert rotated["user"]["id"] == str(user.id)

    old_refresh_again_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original["refresh_token"]},
    )
    assert old_refresh_again_resp.status_code == 401, old_refresh_again_resp.text
    assert old_refresh_again_resp.json()["error"]["code"] == "REFRESH_TOKEN_REUSE"

    rows = (
        db_session.query(RefreshTokenORM)
        .filter(
            RefreshTokenORM.company_id == company_id,
            RefreshTokenORM.user_id == user.id,
        )
        .all()
    )
    assert len(rows) == 2
    assert sum(1 for r in rows if r.revoked_at is not None) == 2
    rotation_row = next(r for r in rows if r.revoke_reason == "ROTATION")
    assert rotation_row.last_used_at is not None
    assert rotation_row.device_id == "rotate-device-a"
    assert rotation_row.ip_address == "testclient"
    assert rotation_row.user_agent == "DimaxRotate/2.0"
    replay_revoked = next(r for r in rows if r.revoke_reason == "REPLAY_DETECTED")
    assert replay_revoked.device_id == "rotate-device-a"
    assert replay_revoked.issued_at is not None
    assert replay_revoked.last_used_at is not None
    assert replay_revoked.ip_address == "testclient"
    assert replay_revoked.user_agent == "DimaxRotate/2.0"


def test_refresh_rejects_user_deactivated_after_login(
    client, db_session, company_id, make_user
):
    password = "DeactivateAfterLogin123"
    user = make_user(role=UserRole.ADMIN, password=password)
    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
            "device_id": "deactivated-refresh-device",
        },
    )
    assert login_resp.status_code == 200, login_resp.text
    refresh_token = login_resp.json()["refresh_token"]

    user.is_active = False
    user.status = "INACTIVE"
    db_session.commit()

    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": refresh_token,
            "device_id": "deactivated-refresh-device",
        },
    )
    assert refresh_resp.status_code == 401, refresh_resp.text
    assert refresh_resp.json()["error"]["code"] == "UNAUTHORIZED"

    sessions = (
        db_session.query(RefreshTokenORM)
        .filter(
            RefreshTokenORM.company_id == company_id,
            RefreshTokenORM.user_id == user.id,
        )
        .all()
    )
    assert len(sessions) == 1

def test_logout_refresh_revokes_token(client, company_id, make_user):
    password = "LogoutPass123"
    user = make_user(role=UserRole.ADMIN, password=password)

    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
            "device_id": "logout-refresh-device",
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
    assert refresh_again_resp.status_code == 401, refresh_again_resp.text
    assert refresh_again_resp.json()["error"]["code"] == "REFRESH_TOKEN_REUSE"


def test_logout_all_revokes_all_active_sessions(client, company_id, make_user):
    password = "LogoutAllPass123"  # gitleaks:allow - deterministic test credential
    user = make_user(role=UserRole.ADMIN, password=password)

    login_a = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
            "device_id": "logout-all-device-a",
        },
    )
    login_b = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
            "device_id": "logout-all-device-b",
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
    assert refresh_a_resp.status_code == 401, refresh_a_resp.text
    assert refresh_b_resp.status_code == 401, refresh_b_resp.text
    assert refresh_a_resp.json()["error"]["code"] == "REFRESH_TOKEN_REUSE"
    assert refresh_b_resp.json()["error"]["code"] == "REFRESH_TOKEN_REUSE"


def test_logout_revokes_active_refresh_sessions(client, db_session, company_id, make_user):
    password = "LogoutAccessPass123"
    user = make_user(role=UserRole.ADMIN, password=password)

    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": password,
            "device_id": "logout-device",
        },
    )
    assert login_resp.status_code == 200, login_resp.text
    access_token = login_resp.json()["access_token"]
    refresh_token = login_resp.json()["refresh_token"]

    logout_resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_resp.status_code == 200, logout_resp.text
    assert logout_resp.json()["ok"] is True
    assert logout_resp.json()["revoked_count"] >= 1

    refresh_again_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_again_resp.status_code == 401, refresh_again_resp.text
    assert refresh_again_resp.json()["error"]["code"] == "REFRESH_TOKEN_REUSE"


def test_refresh_rejects_legacy_non_bcrypt_session_hash(
    client, db_session, company_id, make_user
):
    user = make_user(role=UserRole.ADMIN, password="LegacyCutover123")
    refresh_token, refresh_payload = create_refresh_token(
        user_id=user.id,
        company_id=company_id,
        role=user.role.value,
    )
    db_session.add(
        RefreshTokenORM(
            company_id=company_id,
            user_id=user.id,
            jti=refresh_payload["jti"],
            token_hash=hashlib.sha256(refresh_token.encode("utf-8")).hexdigest(),
            device_id="legacy-device",
            expires_at=datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc),
        )
    )
    db_session.commit()

    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["code"] == "REFRESH_TOKEN_REUSE"

    db_session.expire_all()
    row = (
        db_session.query(RefreshTokenORM)
        .filter(
            RefreshTokenORM.company_id == company_id,
            RefreshTokenORM.user_id == user.id,
        )
        .one()
    )
    assert row.revoked_at is not None
    assert row.revoke_reason == "REPLAY_DETECTED"


def test_refresh_rotates_existing_bcrypt_session(
    client, db_session, company_id, make_user
):
    user = make_user(role=UserRole.ADMIN, password="BcryptCutover123")
    refresh_token, refresh_payload = create_refresh_token(
        user_id=user.id,
        company_id=company_id,
        role=user.role.value,
    )
    legacy_hash = bcrypt.hashpw(
        refresh_token.encode("utf-8")[:72],
        bcrypt.gensalt(rounds=12),
    ).decode("ascii")
    db_session.add(
        RefreshTokenORM(
            company_id=company_id,
            user_id=user.id,
            jti=refresh_payload["jti"],
            token_hash=legacy_hash,
            device_id="bcrypt-cutover-device",
            expires_at=datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc),
        )
    )
    db_session.commit()

    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    old_row = (
        db_session.query(RefreshTokenORM)
        .filter(
            RefreshTokenORM.company_id == company_id,
            RefreshTokenORM.jti == refresh_payload["jti"],
        )
        .one()
    )
    assert old_row.revoked_at is not None
    assert old_row.revoke_reason == "ROTATION"

    new_row = (
        db_session.query(RefreshTokenORM)
        .filter(
            RefreshTokenORM.company_id == company_id,
            RefreshTokenORM.jti != refresh_payload["jti"],
        )
        .order_by(RefreshTokenORM.created_at.desc())
        .first()
    )
    assert new_row is not None
    assert new_row.token_hash.startswith("sha256:")


def test_login_rate_limit_returns_429(client_raw, monkeypatch):
    rate_limit._reset_rate_limits_for_tests()
    monkeypatch.setattr(settings, "AUTH_LOGIN_RL_WINDOW_SEC", 60)
    monkeypatch.setattr(settings, "AUTH_LOGIN_RL_MAX_REQ", 2)

    payload = {
        "company_id": str(uuid.uuid4()),
        "email": "nobody@example.com",
        "password": "secret123",
        "device_id": "rl-login-device",
    }
    r1 = client_raw.post("/api/v1/auth/login", json=payload)
    r2 = client_raw.post("/api/v1/auth/login", json=payload)
    r3 = client_raw.post("/api/v1/auth/login", json=payload)

    assert r1.status_code == 401, r1.text
    assert r2.status_code == 401, r2.text
    assert r3.status_code == 429, r3.text
    assert r3.json()["error"]["code"] == "TOO_MANY_REQUESTS"
    assert r3.json()["error"]["message"] == "Too many requests. Slow down."

    rate_limit._reset_rate_limits_for_tests()


def test_refresh_rate_limit_returns_429(client_raw, monkeypatch):
    rate_limit._reset_rate_limits_for_tests()
    monkeypatch.setattr(settings, "AUTH_REFRESH_RL_WINDOW_SEC", 60)
    monkeypatch.setattr(settings, "AUTH_REFRESH_RL_MAX_REQ", 2)

    payload = {"refresh_token": "invalid-refresh-token"}
    r1 = client_raw.post("/api/v1/auth/refresh", json=payload)
    r2 = client_raw.post("/api/v1/auth/refresh", json=payload)
    r3 = client_raw.post("/api/v1/auth/refresh", json=payload)

    assert r1.status_code == 403, r1.text
    assert r2.status_code == 403, r2.text
    assert r3.status_code == 429, r3.text
    assert r3.json()["error"]["code"] == "TOO_MANY_REQUESTS"
    assert r3.json()["error"]["message"] == "Too many requests. Slow down."

    rate_limit._reset_rate_limits_for_tests()
