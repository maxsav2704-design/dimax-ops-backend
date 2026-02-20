from __future__ import annotations


def test_installers_crud_flow(client):
    create_payload = {
        "full_name": "Ivan Petrov",
        "phone": "+10000000001",
        "email": "ivan.petrov@example.com",
        "address": "Lenina 1",
        "passport_id": "AB123456",
        "notes": "test record",
        "status": "ACTIVE",
        "is_active": True,
    }
    create_resp = client.post("/api/v1/admin/installers", json=create_payload)
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    installer_id = created["id"]
    assert created["full_name"] == create_payload["full_name"]
    assert created["phone"] == create_payload["phone"]

    list_resp = client.get("/api/v1/admin/installers")
    assert list_resp.status_code == 200, list_resp.text
    listed_ids = [row["id"] for row in list_resp.json()]
    assert installer_id in listed_ids

    get_resp = client.get(f"/api/v1/admin/installers/{installer_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == installer_id

    delete_resp = client.delete(f"/api/v1/admin/installers/{installer_id}")
    assert delete_resp.status_code == 204, delete_resp.text

    get_deleted_resp = client.get(f"/api/v1/admin/installers/{installer_id}")
    assert get_deleted_resp.status_code == 404, get_deleted_resp.text

    list_after_delete_resp = client.get("/api/v1/admin/installers")
    assert list_after_delete_resp.status_code == 200, list_after_delete_resp.text
    listed_after_delete_ids = [row["id"] for row in list_after_delete_resp.json()]
    assert installer_id not in listed_after_delete_ids
