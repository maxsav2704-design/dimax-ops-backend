from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import jwt as token_service
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.identity.domain.enums import UserRole


def _login(client, company_id, user):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(company_id),
            "email": user.email,
            "password": "SessionExpiry123",
            "device_id": "expiry-regression",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _expired_token(monkeypatch, user, company_id, *, refresh=False):
    past = datetime.now(timezone.utc) - timedelta(days=365)
    with monkeypatch.context() as context:
        context.setattr(token_service, "utcnow", lambda: past)
        create = token_service.create_refresh_token if refresh else token_service.create_access_token
        token, _ = create(user_id=user.id, company_id=company_id, role=user.role.value)
    return token


def _refresh(client, token):
    return client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": token, "device_id": "expiry-regression"},
    )


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.INSTALLER])
def test_expired_access_returns_401_and_valid_refresh_recovers_session(
    client_raw, company_id, make_user, monkeypatch, role
):
    user = make_user(role=role, password="SessionExpiry123")
    pair = _login(client_raw, company_id, user)
    expired = _expired_token(monkeypatch, user, company_id)

    rejected = client_raw.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert rejected.status_code == 401, rejected.text
    assert rejected.json()["error"]["code"] == "UNAUTHORIZED"

    renewed = _refresh(client_raw, pair["refresh_token"])
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["refresh_token"] != pair["refresh_token"]
    accepted = client_raw.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {renewed.json()['access_token']}"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["id"] == str(user.id)
    assert accepted.json()["company_id"] == str(company_id)
    assert accepted.json()["role"] == role.value

    replay = _refresh(client_raw, pair["refresh_token"])
    assert replay.status_code == 401, replay.text
    assert replay.json()["error"]["code"] == "REFRESH_TOKEN_REUSE"


def test_expired_refresh_is_unauthorized(client_raw, company_id, make_user, monkeypatch):
    user = make_user(role=UserRole.ADMIN, password="SessionExpiry123")
    expired = _expired_token(monkeypatch, user, company_id, refresh=True)
    response = _refresh(client_raw, expired)
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_expired_upload_can_be_replayed_after_refresh_without_duplicate_doors(
    client_raw, db_session, company_id, make_user, monkeypatch
):
    user = make_user(role=UserRole.ADMIN, password="SessionExpiry123")
    pair = _login(client_raw, company_id, user)
    headers = {"Authorization": f"Bearer {pair['access_token']}"}
    project = client_raw.post(
        "/api/v1/admin/projects", headers=headers, json={"name": "Expired upload regression"}
    )
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]
    door_type = client_raw.post(
        "/api/v1/admin/door-types", headers=headers,
        json={"code": "entrance", "name": "Entrance", "is_active": True},
    )
    assert door_type.status_code == 201, door_type.text
    path = f"/api/v1/admin/projects/{project_id}/doors/import-upload"
    content = b"unit_label,door_type,qty,price\nA-101,entrance,1,1000\n"

    def upload(token):
        return client_raw.post(
            path, headers={"Authorization": f"Bearer {token}"},
            files={"file": ("doors.csv", content, "text/csv")},
            data={"analyze_only": "false", "create_missing_door_types": "false"},
        )

    rejected = upload(_expired_token(monkeypatch, user, company_id))
    assert rejected.status_code == 401, rejected.text
    assert db_session.query(DoorORM).filter(DoorORM.company_id == company_id).count() == 0
    renewed = _refresh(client_raw, pair["refresh_token"])
    assert renewed.status_code == 200, renewed.text
    token = renewed.json()["access_token"]
    imported = upload(token)
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 1
    repeated = upload(token)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["idempotency_hit"] is True
    assert db_session.query(DoorORM).filter(DoorORM.company_id == company_id).count() == 1
