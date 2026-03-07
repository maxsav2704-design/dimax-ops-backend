from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal


def test_installer_rates_unique_and_delete_flow(client, make_installer, make_door_type):
    installer = make_installer(full_name="Rate Installer", phone="+10000000002")
    door_type = make_door_type(name="Main Door")

    payload = {
        "installer_id": str(installer.id),
        "door_type_id": str(door_type.id),
        "price": "150.00",
        "effective_from": "2026-01-01T00:00:00Z",
    }

    create_resp = client.post("/api/v1/admin/installer-rates", json=payload)
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    rate_id = created["id"]
    assert created["installer_id"] == payload["installer_id"]
    assert created["door_type_id"] == payload["door_type_id"]
    assert created["price"] == payload["price"]
    assert created["effective_from"] in {
        payload["effective_from"],
        payload["effective_from"].replace("Z", "+00:00"),
    }

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


def test_installer_rates_bulk_set_price_and_delete_flow(
    client,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="Bulk Rates Installer", phone="+10000000025")
    door_type_a = make_door_type(name="Bulk Door A")
    door_type_b = make_door_type(name="Bulk Door B")

    create_a = client.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type_a.id),
            "price": "120.00",
        },
    )
    assert create_a.status_code == 201, create_a.text
    rate_a = create_a.json()

    create_b = client.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type_b.id),
            "price": "140.00",
        },
    )
    assert create_b.status_code == 201, create_b.text
    rate_b = create_b.json()
    latest_existing_effective_from = max(
        datetime.fromisoformat(rate_a["effective_from"].replace("Z", "+00:00")),
        datetime.fromisoformat(rate_b["effective_from"].replace("Z", "+00:00")),
    )
    bulk_effective_from = (
        latest_existing_effective_from + timedelta(days=1)
    ).isoformat()

    bulk_set = client.post(
        "/api/v1/admin/installer-rates/bulk",
        json={
            "ids": [rate_a["id"], rate_b["id"], str(uuid.uuid4())],
            "operation": "set_price",
            "price": "199.50",
            "effective_from": bulk_effective_from,
        },
    )
    assert bulk_set.status_code == 200, bulk_set.text
    assert bulk_set.json() == {"affected": 2, "not_found": 1, "unchanged": 0}

    get_a = client.get(f"/api/v1/admin/installer-rates/{rate_a['id']}")
    assert get_a.status_code == 200, get_a.text
    assert Decimal(str(get_a.json()["price"])) == Decimal("120.00")

    get_b = client.get(f"/api/v1/admin/installer-rates/{rate_b['id']}")
    assert get_b.status_code == 200, get_b.text
    assert Decimal(str(get_b.json()["price"])) == Decimal("140.00")

    list_resp = client.get(
        f"/api/v1/admin/installer-rates?installer_id={installer.id}"
    )
    assert list_resp.status_code == 200, list_resp.text
    rows = list_resp.json()
    assert len(rows) == 4
    latest_by_door: dict[str, dict] = {}
    for row in rows:
        latest_by_door.setdefault(row["door_type_id"], row)
    assert Decimal(str(latest_by_door[str(door_type_a.id)]["price"])) == Decimal("199.50")
    assert Decimal(str(latest_by_door[str(door_type_b.id)]["price"])) == Decimal("199.50")
    assert latest_by_door[str(door_type_a.id)]["effective_from"] in {
        bulk_effective_from,
        bulk_effective_from.replace("+00:00", "Z"),
    }

    bulk_same = client.post(
        "/api/v1/admin/installer-rates/bulk",
        json={
            "ids": [rate_a["id"]],
            "operation": "set_price",
            "price": "199.50",
            "effective_from": bulk_effective_from,
        },
    )
    assert bulk_same.status_code == 200, bulk_same.text
    assert bulk_same.json() == {"affected": 0, "not_found": 0, "unchanged": 1}

    bulk_delete = client.post(
        "/api/v1/admin/installer-rates/bulk",
        json={
            "ids": [rate_a["id"], str(uuid.uuid4())],
            "operation": "delete",
        },
    )
    assert bulk_delete.status_code == 200, bulk_delete.text
    assert bulk_delete.json() == {"affected": 1, "not_found": 1, "unchanged": 0}

    deleted_a = client.get(f"/api/v1/admin/installer-rates/{rate_a['id']}")
    assert deleted_a.status_code == 404, deleted_a.text

    remaining_b = client.get(f"/api/v1/admin/installer-rates/{rate_b['id']}")
    assert remaining_b.status_code == 200, remaining_b.text
    assert Decimal(str(remaining_b.json()["price"])) == Decimal("140.00")


def test_installer_rates_support_effective_from_versioning(
    client,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="Versioned Rates Installer", phone="+10000000028")
    door_type = make_door_type(name="Versioned Door")
    older_from = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc).isoformat()
    newer_from = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc).isoformat()

    create_old = client.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type.id),
            "price": "100.00",
            "effective_from": older_from,
        },
    )
    assert create_old.status_code == 201, create_old.text

    create_new = client.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type.id),
            "price": "130.00",
            "effective_from": newer_from,
        },
    )
    assert create_new.status_code == 201, create_new.text

    list_resp = client.get(
        f"/api/v1/admin/installer-rates?installer_id={installer.id}&door_type_id={door_type.id}"
    )
    assert list_resp.status_code == 200, list_resp.text
    rows = list_resp.json()
    assert len(rows) == 2
    assert Decimal(str(rows[0]["price"])) == Decimal("130.00")
    assert Decimal(str(rows[1]["price"])) == Decimal("100.00")


def test_installer_rates_timeline_supports_as_of_resolution(
    client,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="Timeline Installer", phone="+10000000030")
    door_type = make_door_type(name="Timeline Door")

    v1_from = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc).isoformat()
    v2_from = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc).isoformat()
    v3_from = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc).isoformat()

    for price, starts_at in (("100.00", v1_from), ("120.00", v2_from), ("150.00", v3_from)):
        create_resp = client.post(
            "/api/v1/admin/installer-rates",
            json={
                "installer_id": str(installer.id),
                "door_type_id": str(door_type.id),
                "price": price,
                "effective_from": starts_at,
            },
        )
        assert create_resp.status_code == 201, create_resp.text

    as_of = "2026-02-15T00:00:00Z"
    timeline_resp = client.get(
        "/api/v1/admin/installer-rates/timeline",
        params={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type.id),
            "as_of": as_of,
        },
    )
    assert timeline_resp.status_code == 200, timeline_resp.text
    payload = timeline_resp.json()
    assert payload["installer_id"] == str(installer.id)
    assert payload["door_type_id"] == str(door_type.id)
    assert payload["as_of"] in {as_of, as_of.replace("Z", "+00:00")}
    assert len(payload["versions"]) == 3
    assert Decimal(str(payload["versions"][0]["price"])) == Decimal("150.00")
    assert Decimal(str(payload["versions"][1]["price"])) == Decimal("120.00")
    assert Decimal(str(payload["versions"][2]["price"])) == Decimal("100.00")
    assert payload["effective_rate"] is not None
    assert Decimal(str(payload["effective_rate"]["price"])) == Decimal("120.00")
