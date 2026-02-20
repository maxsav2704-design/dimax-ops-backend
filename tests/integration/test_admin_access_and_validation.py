from __future__ import annotations

import uuid


def test_admin_installers_list_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/installers")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_admin_installer_rates_list_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/installer-rates")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_admin_installers_link_forbidden_for_installer_role(client_installer):
    resp = client_installer.post(
        f"/api/v1/admin/installers/{uuid.uuid4()}/link-user",
        json={"user_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


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


def test_update_installer_rate_validation_returns_422(client):
    resp = client.patch(
        f"/api/v1/admin/installer-rates/{uuid.uuid4()}",
        json={"price": "-5.00"},
    )
    assert resp.status_code == 422, resp.text
