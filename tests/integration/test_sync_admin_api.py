from __future__ import annotations

import uuid

from app.modules.identity.domain.enums import UserRole


def test_sync_admin_states_and_stats_return_payload(client_admin_real_uow):
    states_resp = client_admin_real_uow.get("/api/v1/admin/sync/states")
    assert states_resp.status_code == 200, states_resp.text
    assert isinstance(states_resp.json(), list)

    stats_resp = client_admin_real_uow.get("/api/v1/admin/sync/stats")
    assert stats_resp.status_code == 200, stats_resp.text
    body = stats_resp.json()
    assert "total_installers" in body
    assert "active_last_30_days" in body


def test_sync_admin_reset_endpoints_success(client_admin_real_uow, make_user):
    user = make_user(role=UserRole.INSTALLER, is_active=True)

    create_installer_resp = client_admin_real_uow.post(
        "/api/v1/admin/installers",
        json={
            "full_name": "Sync Installer",
            "phone": "+10000000031",
            "status": "ACTIVE",
            "is_active": True,
            "user_id": str(user.id),
        },
    )
    assert create_installer_resp.status_code == 201, create_installer_resp.text
    installer_id = create_installer_resp.json()["id"]

    reset_new_resp = client_admin_real_uow.post(
        f"/api/v1/admin/sync/states/{user.id}/reset"
    )
    assert reset_new_resp.status_code == 200, reset_new_resp.text
    reset_new_body = reset_new_resp.json()
    assert reset_new_body["installer_id"] == installer_id
    assert reset_new_body["last_cursor_ack"] == 0
    assert reset_new_body["lag"] >= 0

    reset_legacy_resp = client_admin_real_uow.post(
        f"/api/v1/admin/sync/reset/{installer_id}"
    )
    assert reset_legacy_resp.status_code == 200, reset_legacy_resp.text
    assert reset_legacy_resp.json() == {"status": "reset_ok"}


def test_sync_admin_reset_not_found_returns_domain_error(client_admin_real_uow):
    missing_id = uuid.uuid4()

    reset_new_resp = client_admin_real_uow.post(
        f"/api/v1/admin/sync/states/{missing_id}/reset"
    )
    assert reset_new_resp.status_code == 404, reset_new_resp.text
    assert reset_new_resp.json()["error"]["code"] == "NOT_FOUND"

    reset_legacy_resp = client_admin_real_uow.post(
        f"/api/v1/admin/sync/reset/{missing_id}"
    )
    assert reset_legacy_resp.status_code == 404, reset_legacy_resp.text
    assert reset_legacy_resp.json()["error"]["code"] == "NOT_FOUND"


def test_sync_admin_endpoints_forbidden_for_installer(client_installer):
    states_resp = client_installer.get("/api/v1/admin/sync/states")
    assert states_resp.status_code == 403, states_resp.text
    assert states_resp.json()["error"]["code"] == "FORBIDDEN"

    stats_resp = client_installer.get("/api/v1/admin/sync/stats")
    assert stats_resp.status_code == 403, stats_resp.text
    assert stats_resp.json()["error"]["code"] == "FORBIDDEN"

    reset_resp = client_installer.post(
        f"/api/v1/admin/sync/states/{uuid.uuid4()}/reset"
    )
    assert reset_resp.status_code == 403, reset_resp.text
    assert reset_resp.json()["error"]["code"] == "FORBIDDEN"
