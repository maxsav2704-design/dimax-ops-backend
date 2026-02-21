from __future__ import annotations

from decimal import Decimal


def test_admin_installers_list_supports_q_and_is_active_and_pagination(
    client, make_installer
):
    make_installer(full_name="Alpha Active", phone="+10000001001", is_active=True)
    make_installer(full_name="Alpha Inactive", phone="+10000001002", is_active=False)
    make_installer(full_name="Beta Active", phone="+10000001003", is_active=True)

    q_resp = client.get("/api/v1/admin/installers?q=Alpha")
    assert q_resp.status_code == 200, q_resp.text
    q_items = q_resp.json()
    assert len(q_items) == 2
    assert all("Alpha" in x["full_name"] for x in q_items)

    active_resp = client.get("/api/v1/admin/installers?is_active=true")
    assert active_resp.status_code == 200, active_resp.text
    active_items = active_resp.json()
    assert len(active_items) == 2
    assert all(x["is_active"] is True for x in active_items)

    page1_resp = client.get("/api/v1/admin/installers?limit=1&offset=0")
    page2_resp = client.get("/api/v1/admin/installers?limit=1&offset=1")
    assert page1_resp.status_code == 200, page1_resp.text
    assert page2_resp.status_code == 200, page2_resp.text
    page1 = page1_resp.json()
    page2 = page2_resp.json()
    assert len(page1) == 1
    assert len(page2) == 1
    assert page1[0]["id"] != page2[0]["id"]


def test_admin_installer_rates_list_supports_filters_and_pagination(
    client, make_installer, make_door_type
):
    installer_a = make_installer(full_name="Rates Installer A", phone="+10000001101")
    installer_b = make_installer(full_name="Rates Installer B", phone="+10000001102")
    door_a = make_door_type(name="Door A")
    door_b = make_door_type(name="Door B")
    door_c = make_door_type(name="Door C")

    payloads = [
        {
            "installer_id": str(installer_a.id),
            "door_type_id": str(door_a.id),
            "price": str(Decimal("100.00")),
        },
        {
            "installer_id": str(installer_a.id),
            "door_type_id": str(door_b.id),
            "price": str(Decimal("110.00")),
        },
        {
            "installer_id": str(installer_b.id),
            "door_type_id": str(door_c.id),
            "price": str(Decimal("120.00")),
        },
    ]
    for payload in payloads:
        create_resp = client.post("/api/v1/admin/installer-rates", json=payload)
        assert create_resp.status_code == 201, create_resp.text

    installer_filter_resp = client.get(
        f"/api/v1/admin/installer-rates?installer_id={installer_a.id}"
    )
    assert installer_filter_resp.status_code == 200, installer_filter_resp.text
    installer_filtered = installer_filter_resp.json()
    assert len(installer_filtered) == 2
    assert all(x["installer_id"] == str(installer_a.id) for x in installer_filtered)

    door_filter_resp = client.get(
        f"/api/v1/admin/installer-rates?door_type_id={door_c.id}"
    )
    assert door_filter_resp.status_code == 200, door_filter_resp.text
    door_filtered = door_filter_resp.json()
    assert len(door_filtered) == 1
    assert door_filtered[0]["door_type_id"] == str(door_c.id)

    page1_resp = client.get("/api/v1/admin/installer-rates?limit=1&offset=0")
    page2_resp = client.get("/api/v1/admin/installer-rates?limit=1&offset=1")
    assert page1_resp.status_code == 200, page1_resp.text
    assert page2_resp.status_code == 200, page2_resp.text
    page1 = page1_resp.json()
    page2 = page2_resp.json()
    assert len(page1) == 1
    assert len(page2) == 1
    assert page1[0]["id"] != page2[0]["id"]
