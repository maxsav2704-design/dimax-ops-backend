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
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_admin_installer_rates_timeline_forbidden_for_installer_role(client_installer):
    resp = client_installer.get(
        f"/api/v1/admin/installer-rates/timeline?installer_id={uuid.uuid4()}&door_type_id={uuid.uuid4()}"
    )
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
