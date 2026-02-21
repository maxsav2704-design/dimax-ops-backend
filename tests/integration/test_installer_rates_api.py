from __future__ import annotations


def test_installer_rates_unique_and_delete_flow(client, make_installer, make_door_type):
    installer = make_installer(full_name="Rate Installer", phone="+10000000002")
    door_type = make_door_type(name="Main Door")

    payload = {
        "installer_id": str(installer.id),
        "door_type_id": str(door_type.id),
        "price": "150.00",
    }

    create_resp = client.post("/api/v1/admin/installer-rates", json=payload)
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    rate_id = created["id"]
    assert created["installer_id"] == payload["installer_id"]
    assert created["door_type_id"] == payload["door_type_id"]
    assert created["price"] == payload["price"]

    duplicate_resp = client.post("/api/v1/admin/installer-rates", json=payload)
    assert duplicate_resp.status_code == 409, duplicate_resp.text
    assert duplicate_resp.json()["error"]["code"] == "CONFLICT"

    list_resp = client.get(
        f"/api/v1/admin/installer-rates?installer_id={payload['installer_id']}"
    )
    assert list_resp.status_code == 200, list_resp.text
    rates = list_resp.json()
    assert len(rates) == 1
    assert rates[0]["id"] == rate_id

    delete_resp = client.delete(f"/api/v1/admin/installer-rates/{rate_id}")
    assert delete_resp.status_code == 204, delete_resp.text

    get_deleted_resp = client.get(f"/api/v1/admin/installer-rates/{rate_id}")
    assert get_deleted_resp.status_code == 404, get_deleted_resp.text
    assert get_deleted_resp.json()["error"]["code"] == "NOT_FOUND"
