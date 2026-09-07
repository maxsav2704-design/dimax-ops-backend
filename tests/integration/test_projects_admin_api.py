from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.sync.domain.enums import SyncChangeType
from app.modules.sync.infrastructure.models import SyncChangeLogORM


def _create_project(client_admin_real_uow, name: str, address: str) -> str:
    resp = client_admin_real_uow.post(
        "/api/v1/admin/projects",
        json={
            "name": name,
            "address": address,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_projects_crud_and_details_flow(client_admin_real_uow):
    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects",
        json={
            "code": "PRJ-CRUD-A",
            "name": "Project CRUD A",
            "address": "Main street 1",
            "planned_start_date": "2026-04-01",
            "planned_end_date": "2026-04-30",
            "developer_company": "Builder Ltd",
            "contact_name": "Yael Cohen",
            "contact_phone": "050-123-4567",
            "contact_email": "yael@example.com",
            "developer_phone_alt": "050-123-9999",
            "developer_whatsapp": "050-555-1234",
            "developer_notes": "Gate code 7788",
            "address_street": "Main street",
            "address_building": "1",
            "address_city": "Ashdod",
            "address_entrance": "A",
            "address_lat": "31.801",
            "address_lng": "34.643",
            "address_waze_url": "https://www.waze.com/ul?q=Manual+Override",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    project_id = create_resp.json()["id"]

    details_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}",
        headers={"Accept-Language": "ru"},
    )
    assert details_resp.status_code == 200, details_resp.text
    details = details_resp.json()
    assert details["id"] == project_id
    assert details["name"] == "Project CRUD A"
    assert details["code"] == "PRJ-CRUD-A"
    assert details["planned_start_date"] == "2026-04-01"
    assert details["planned_end_date"] == "2026-04-30"
    assert details["developer_company"] == "Builder Ltd"
    assert details["contact_name"] == "Yael Cohen"
    assert details["contact_phone"] == "+972501234567"
    assert details["developer_phone_alt"] == "+972501239999"
    assert details["developer_whatsapp"] == "+972505551234"
    assert details["developer_notes"] == "Gate code 7788"
    assert details["address"] == "Main street, 1, Ashdod, A"
    assert details["address_details"] == {
        "street": "Main street",
        "building": "1",
        "city": "Ashdod",
        "entrance": "A",
        "lat": "31.801",
        "lng": "34.643",
        "waze_url": "https://www.waze.com/ul?q=Manual+Override",
        "waze_deep_link": "https://waze.com/ul?ll=31.801,34.643&navigate=yes",
    }
    assert details["address_street"] == "Main street"
    assert details["address_city"] == "Ashdod"
    assert details["waze_deep_link"] == "https://waze.com/ul?ll=31.801,34.643&navigate=yes"
    assert details["developer"] == {
        "name": "Builder Ltd",
        "contact_name": "Yael Cohen",
        "phone": "+972501234567",
        "phone_alt": "+972501239999",
        "whatsapp": "+972505551234",
        "email": "yael@example.com",
        "notes": "Gate code 7788",
        "whatsapp_deep_link": details["whatsapp_deep_link"],
        "call_deep_link": "tel:+972501234567",
    }
    assert details["whatsapp_deep_link"] is not None
    assert (
        "%D0%94%D0%BE%D0%B1%D1%80%D1%8B%D0%B9+%D0%B4%D0%B5%D0%BD%D1%8C%2C+"
        "%D0%BF%D0%BE+%D0%BF%D1%80%D0%BE%D0%B5%D0%BA%D1%82%D1%83+Project+CRUD+A+%28PRJ-CRUD-A%29"
    ) in details["whatsapp_deep_link"]
    assert details["call_deep_link"] == "tel:+972501234567"
    assert isinstance(details["doors"], list)
    assert isinstance(details["issues_open"], list)

    update_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/projects/{project_id}",
        json={
            "name": "Project CRUD B",
            "contact_name": "Manager",
            "contact_phone": "0507000000",
            "address_waze_url": "https://www.waze.com/ul?q=Project+CRUD+B",
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["ok"] is True

    updated_details_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}"
    )
    assert updated_details_resp.status_code == 200, updated_details_resp.text
    updated = updated_details_resp.json()
    assert updated["name"] == "Project CRUD B"
    assert updated["contact_name"] == "Manager"
    assert updated["contact_phone"] == "+972507000000"
    assert updated["address_waze_url"] == "https://www.waze.com/ul?q=Project+CRUD+B"
    assert updated["waze_deep_link"] == "https://waze.com/ul?ll=31.801,34.643&navigate=yes"
    assert updated["call_deep_link"] == "tel:+972507000000"

    list_resp = client_admin_real_uow.get("/api/v1/admin/projects")
    assert list_resp.status_code == 200, list_resp.text
    listed_ids = {x["id"] for x in list_resp.json()["items"]}
    assert project_id in listed_ids
    listed_row = next(x for x in list_resp.json()["items"] if x["id"] == project_id)
    assert listed_row["code"] == "PRJ-CRUD-A"

    delete_resp = client_admin_real_uow.delete(f"/api/v1/admin/projects/{project_id}")
    assert delete_resp.status_code == 200, delete_resp.text
    assert delete_resp.json()["ok"] is True

    deleted_details_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}"
    )
    assert deleted_details_resp.status_code == 404, deleted_details_resp.text
    assert deleted_details_resp.json()["error"]["code"] == "NOT_FOUND"


def test_project_lifecycle_enforces_completion_invariants(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects",
        json={
            "name": "Lifecycle Project",
            "address": "Lifecycle Street 1",
            "lifecycle_status": "PLANNED",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    project_id = create_resp.json()["id"]

    details = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}"
    ).json()
    assert details["lifecycle_status"] == "PLANNED"
    assert details["health_status"] == "NORMAL"

    invalid_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/projects/{project_id}",
        json={"lifecycle_status": "UNKNOWN"},
    )
    assert invalid_resp.status_code == 422, invalid_resp.text

    activate_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/projects/{project_id}",
        json={"lifecycle_status": "ACTIVE"},
    )
    assert activate_resp.status_code == 200, activate_resp.text

    door_type = make_door_type(name="Lifecycle Door")
    door = DoorORM(
        company_id=company_id,
        project_id=uuid.UUID(project_id),
        door_type_id=door_type.id,
        unit_label="LIFE-01",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(door)
    db_session.commit()

    blocked_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/projects/{project_id}",
        json={"lifecycle_status": "COMPLETED"},
    )
    assert blocked_resp.status_code == 409, blocked_resp.text
    assert blocked_resp.json()["error"]["code"] == "CONFLICT"
    assert blocked_resp.json()["error"]["meta"]["incomplete_doors"] == 1

    door.status = DoorStatus.CANCELLED
    db_session.commit()
    complete_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/projects/{project_id}",
        json={"lifecycle_status": "COMPLETED"},
    )
    assert complete_resp.status_code == 200, complete_resp.text

    completed = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}"
    ).json()
    assert completed["lifecycle_status"] == "COMPLETED"

    reopen_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/projects/{project_id}",
        json={"lifecycle_status": "ACTIVE"},
    )
    assert reopen_resp.status_code == 200, reopen_resp.text


def test_project_health_is_derived_from_blockers_and_overdue_work(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects",
        json={
            "name": "Derived Health Project",
            "address": "Health Street 1",
            "planned_end_date": (date.today() - timedelta(days=1)).isoformat(),
            "lifecycle_status": "ACTIVE",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    project_id = create_resp.json()["id"]
    door_type = make_door_type(name="Derived Health Door")
    door = DoorORM(
        company_id=company_id,
        project_id=uuid.UUID(project_id),
        door_type_id=door_type.id,
        unit_label="HEALTH-01",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(door)
    db_session.commit()

    recalc_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/projects/{project_id}",
        json={"lifecycle_status": "ACTIVE"},
    )
    assert recalc_resp.status_code == 200, recalc_resp.text
    at_risk = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}"
    ).json()
    assert at_risk["health_status"] == "AT_RISK"
    assert at_risk["status"] == "PROBLEM"

    door.status = DoorStatus.ISSUE_OPEN
    db_session.commit()
    client_admin_real_uow.patch(
        f"/api/v1/admin/projects/{project_id}",
        json={"lifecycle_status": "ACTIVE"},
    )
    blocked = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}"
    ).json()
    assert blocked["health_status"] == "BLOCKED"

    door.status = DoorStatus.CANCELLED
    db_session.commit()
    client_admin_real_uow.patch(
        f"/api/v1/admin/projects/{project_id}",
        json={"lifecycle_status": "ACTIVE"},
    )
    normal = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}"
    ).json()
    assert normal["health_status"] == "NORMAL"
    assert normal["status"] == "OK"

    latest_change = (
        db_session.query(SyncChangeLogORM)
        .filter(
            SyncChangeLogORM.company_id == company_id,
            SyncChangeLogORM.entity_id == uuid.UUID(project_id),
            SyncChangeLogORM.change_type == SyncChangeType.PROJECT_BASE,
        )
        .order_by(SyncChangeLogORM.cursor_id.desc())
        .first()
    )
    assert latest_change is not None
    assert latest_change.payload["lifecycle_status"] == "ACTIVE"
    assert latest_change.payload["health_status"] == "NORMAL"


def test_projects_address_suggestions(client_admin_real_uow):
    resp = client_admin_real_uow.get(
        "/api/v1/admin/projects/address-suggestions",
        params={"q": "Herzl, 14, Ashdod, A"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"]
    item = body["items"][0]
    assert item["street"] == "Herzl"
    assert item["building"] == "14"
    assert item["city"] == "Ashdod"
    assert item["entrance"] == "A"
    assert item["lat"]
    assert item["lng"]


def test_projects_list_supports_q_status_and_pagination(
    client_admin_real_uow, db_session, company_id
):
    p1 = _create_project(client_admin_real_uow, "Alpha One", "Addr A1")
    p2 = _create_project(client_admin_real_uow, "Alpha Two", "Addr A2")
    _create_project(client_admin_real_uow, "Beta One", "Addr B1")

    db_session.execute(
        text(
            "UPDATE projects SET status = :status "
            "WHERE company_id = :cid AND id = :pid"
        ),
        {"status": ProjectStatus.PROBLEM.value, "cid": company_id, "pid": p2},
    )
    db_session.commit()

    q_resp = client_admin_real_uow.get("/api/v1/admin/projects?q=Alpha")
    assert q_resp.status_code == 200, q_resp.text
    q_items = q_resp.json()["items"]
    assert len(q_items) == 2
    assert all("Alpha" in x["name"] for x in q_items)

    status_resp = client_admin_real_uow.get("/api/v1/admin/projects?status=PROBLEM")
    assert status_resp.status_code == 200, status_resp.text
    status_items = status_resp.json()["items"]
    assert len(status_items) >= 1
    assert p2 in {x["id"] for x in status_items}

    page1_resp = client_admin_real_uow.get("/api/v1/admin/projects?limit=1&offset=0")
    page2_resp = client_admin_real_uow.get("/api/v1/admin/projects?limit=1&offset=1")
    assert page1_resp.status_code == 200, page1_resp.text
    assert page2_resp.status_code == 200, page2_resp.text
    page1 = page1_resp.json()["items"]
    page2 = page2_resp.json()["items"]
    assert len(page1) == 1
    assert len(page2) == 1
    assert page1[0]["id"] != page2[0]["id"]
    assert {p1, p2}.issubset({x["id"] for x in q_items})


def test_projects_import_doors_and_assign_installer(
    client_admin_real_uow, make_door_type, make_installer
):
    project_id = _create_project(
        client_admin_real_uow, "Project Import", "Import address"
    )
    door_type = make_door_type(name="Import Door Type")

    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import",
        json={
            "rows": [
                {
                    "door_type_id": str(door_type.id),
                    "unit_label": "A-01",
                    "our_price": str(Decimal("123.45")),
                }
            ]
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 1

    details_resp = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details_resp.status_code == 200, details_resp.text
    details = details_resp.json()
    assert len(details["doors"]) == 1
    door_id = details["doors"][0]["id"]
    assert details["doors"][0]["status"] == DoorStatus.NOT_INSTALLED.value

    installer = make_installer(full_name="Assign Installer", phone="+10000003001")
    assign_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/doors/{door_id}/assign-installer",
        json={"installer_id": str(installer.id)},
    )
    assert assign_resp.status_code == 200, assign_resp.text
    assert assign_resp.json()["ok"] is True

    details_after_assign_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}"
    )
    assert details_after_assign_resp.status_code == 200, details_after_assign_resp.text
    door = details_after_assign_resp.json()["doors"][0]
    assert door["installer_id"] == str(installer.id)


def test_projects_bulk_assign_imported_doors_to_installer_writes_sync(
    client_admin_real_uow,
    db_session,
    make_door_type,
    make_installer,
):
    project_id = _create_project(
        client_admin_real_uow,
        "Project Bulk Assign",
        "Bulk assign address",
    )
    door_type = make_door_type(name="Bulk Assign Door Type")

    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import",
        json={
            "rows": [
                {
                    "door_type_id": str(door_type.id),
                    "unit_label": "B-01",
                    "our_price": "110.00",
                },
                {
                    "door_type_id": str(door_type.id),
                    "unit_label": "B-02",
                    "our_price": "120.00",
                },
            ]
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 2

    details_resp = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details_resp.status_code == 200, details_resp.text
    door_ids = [door["id"] for door in details_resp.json()["doors"]]
    assert len(door_ids) == 2

    installer = make_installer(full_name="Bulk Assign Installer", phone="+10000003002")
    assign_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/doors/bulk-assign-installer",
        json={"door_ids": door_ids, "installer_id": str(installer.id)},
    )
    assert assign_resp.status_code == 200, assign_resp.text
    assert assign_resp.json() == {
        "assigned": 2,
        "skipped": 0,
        "assigned_door_ids": door_ids,
    }

    details_after_resp = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details_after_resp.status_code == 200, details_after_resp.text
    assigned = details_after_resp.json()["doors"]
    assert {door["id"] for door in assigned} == set(door_ids)
    assert {door["installer_id"] for door in assigned} == {str(installer.id)}

    changes = (
        db_session.query(SyncChangeLogORM)
        .filter(SyncChangeLogORM.project_id == uuid.UUID(project_id))
        .all()
    )
    assignment_changes = [
        change
        for change in changes
        if change.change_type == SyncChangeType.PROJECT_ASSIGNMENTS
        and change.installer_id == installer.id
        and change.payload.get("kind") == "assigned_to_you"
    ]
    assert len(assignment_changes) == 1
    assert set(assignment_changes[0].payload["affected_door_ids"]) == set(door_ids)

    project_changes = [
        change
        for change in changes
        if change.change_type == SyncChangeType.PROJECT_BASE
        and change.installer_id == installer.id
    ]
    assert len(project_changes) == 1
    assert project_changes[0].payload["id"] == project_id

    door_changes = [
        change
        for change in changes
        if change.change_type == SyncChangeType.DOOR
        and change.installer_id == installer.id
    ]
    assert {str(change.entity_id) for change in door_changes} == set(door_ids)


def test_projects_bulk_assign_rejects_locked_door_without_partial_update(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
    make_installer,
):
    project_id = uuid.UUID(
        _create_project(
            client_admin_real_uow,
            "Project Bulk Locked",
            "Bulk locked address",
        )
    )
    door_type = make_door_type(name="Bulk Locked Door Type")
    installer = make_installer(full_name="Bulk Locked Installer", phone="+10000003003")
    open_door = DoorORM(
        company_id=company_id,
        project_id=project_id,
        door_type_id=door_type.id,
        unit_label="BL-01",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    locked_door = DoorORM(
        company_id=company_id,
        project_id=project_id,
        door_type_id=door_type.id,
        unit_label="BL-02",
        our_price=Decimal("100.00"),
        status=DoorStatus.INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=True,
    )
    db_session.add_all([open_door, locked_door])
    db_session.commit()

    assign_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/doors/bulk-assign-installer",
        json={
            "door_ids": [str(open_door.id), str(locked_door.id)],
            "installer_id": str(installer.id),
        },
    )
    assert assign_resp.status_code == 409, assign_resp.text
    assert assign_resp.json()["error"]["code"] == "CONFLICT"

    db_session.expire_all()
    doors = (
        db_session.query(DoorORM)
        .filter(DoorORM.id.in_([open_door.id, locked_door.id]))
        .all()
    )
    assert {door.installer_id for door in doors} == {None}


def test_projects_bulk_assign_rejects_cross_project_batch_without_partial_update(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
    make_installer,
):
    project_a_id = uuid.UUID(
        _create_project(
            client_admin_real_uow,
            "Project Bulk Cross A",
            "Bulk cross address A",
        )
    )
    project_b_id = uuid.UUID(
        _create_project(
            client_admin_real_uow,
            "Project Bulk Cross B",
            "Bulk cross address B",
        )
    )
    door_type = make_door_type(name="Bulk Cross Door Type")
    installer = make_installer(full_name="Bulk Cross Installer", phone="+10000003004")
    door_a = DoorORM(
        company_id=company_id,
        project_id=project_a_id,
        door_type_id=door_type.id,
        unit_label="BC-A",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    door_b = DoorORM(
        company_id=company_id,
        project_id=project_b_id,
        door_type_id=door_type.id,
        unit_label="BC-B",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add_all([door_a, door_b])
    db_session.commit()

    assign_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/doors/bulk-assign-installer",
        json={
            "door_ids": [str(door_a.id), str(door_b.id)],
            "installer_id": str(installer.id),
        },
    )
    assert assign_resp.status_code == 409, assign_resp.text
    assert assign_resp.json()["error"]["code"] == "CONFLICT"

    db_session.expire_all()
    doors = (
        db_session.query(DoorORM)
        .filter(DoorORM.id.in_([door_a.id, door_b.id]))
        .all()
    )
    assert {door.installer_id for door in doors} == {None}


def test_project_manual_door_from_library(
    client_admin_real_uow,
    make_installer,
):
    project_id = _create_project(
        client_admin_real_uow,
        "Project Manual Library",
        "Manual library address",
    )
    installer = make_installer(full_name="Manual Door Installer", phone="+97250003003")

    create_product = client_admin_real_uow.post(
        "/api/v1/admin/library",
        json={
            "sku": f"SKU-{uuid.uuid4().hex[:8]}",
            "name_ru": "Entrance door RU",
            "name_he": "Entrance door HE",
            "install_type": "Entrance Door",
            "manufacturer": "DIMAX",
            "unit": "piece",
        },
    )
    assert create_product.status_code == 201, create_product.text
    product = create_product.json()

    list_products = client_admin_real_uow.get("/api/v1/admin/library?status=ACTIVE")
    assert list_products.status_code == 200, list_products.text
    assert product["id"] in {row["id"] for row in list_products.json()["items"]}

    patch_product = client_admin_real_uow.patch(
        f"/api/v1/admin/library/{product['id']}",
        json={"manufacturer": "DIMAX Updated"},
    )
    assert patch_product.status_code == 200, patch_product.text
    assert patch_product.json()["manufacturer"] == "DIMAX Updated"

    create_door = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors",
        json={
            "product_id": product["id"],
            "door_code": "A-01-D",
            "unit": "A-01",
            "floor": "1",
            "location_code": "entrance",
            "order_number": "ORD-MANUAL-1",
            "is_critical": True,
            "assigned_installer_id": str(installer.id),
        },
    )
    assert create_door.status_code == 201, create_door.text
    door = create_door.json()
    assert door["unit_label"] == "A-01"
    assert door["door_marking"] == "A-01-D"
    assert door["status"] == DoorStatus.NOT_INSTALLED.value
    assert door["installer_id"] == str(installer.id)

    duplicate = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors",
        json={
            "product_id": product["id"],
            "door_code": "A-01-D",
            "unit": "A-01",
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "CONFLICT"

    layout_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}/doors/layout"
    )
    assert layout_resp.status_code == 200, layout_resp.text
    layout = layout_resp.json()
    assert layout["total_doors"] == 1
    assert layout["buckets"][0]["doors"][0]["id"] == door["id"]


def test_project_doors_layout_groups_by_floor_location_marking(
    client_admin_real_uow, make_door_type
):
    project_id = _create_project(
        client_admin_real_uow,
        "Project Layout",
        "Layout address",
    )
    door_type = make_door_type(name="Layout Door Type")

    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import",
        json={
            "rows": [
                {
                    "door_type_id": str(door_type.id),
                    "unit_label": "A-3-12-D12",
                    "our_price": "100.00",
                    "order_number": "AZ-LAYOUT-1",
                    "house_number": "A",
                    "floor_label": "3",
                    "apartment_number": "12",
                    "location_code": "dira",
                    "door_marking": "D12",
                },
                {
                    "door_type_id": str(door_type.id),
                    "unit_label": "A-3-13-M13",
                    "our_price": "100.00",
                    "order_number": "AZ-LAYOUT-1",
                    "house_number": "A",
                    "floor_label": "3",
                    "apartment_number": "13",
                    "location_code": "mamad",
                    "door_marking": "M13",
                },
                {
                    "door_type_id": str(door_type.id),
                    "unit_label": "A-3-14-M13",
                    "our_price": "100.00",
                    "order_number": "AZ-LAYOUT-1",
                    "house_number": "A",
                    "floor_label": "3",
                    "apartment_number": "14",
                    "location_code": "mamad",
                    "door_marking": "M13",
                },
            ]
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 3

    layout_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}/doors/layout"
    )
    assert layout_resp.status_code == 200, layout_resp.text
    body = layout_resp.json()
    assert body["project_id"] == project_id
    assert body["total_doors"] == 3
    assert len(body["buckets"]) == 2

    mamad_bucket = next(
        b
        for b in body["buckets"]
        if b["location_code"] == "mamad" and b["door_marking"] == "M13"
    )
    assert mamad_bucket["total"] == 2
    assert mamad_bucket["order_number"] == "AZ-LAYOUT-1"
    assert mamad_bucket["status_breakdown"][DoorStatus.NOT_INSTALLED.value] == 2
    assert [d["apartment_number"] for d in mamad_bucket["doors"]] == ["13", "14"]


def test_project_details_and_layout_can_filter_by_order_number(
    client_admin_real_uow, make_door_type
):
    project_id = _create_project(
        client_admin_real_uow,
        "Project Order Filter",
        "Order filter address",
    )
    door_type = make_door_type(name="Order Filter Door Type")

    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import",
        json={
            "rows": [
                {
                    "door_type_id": str(door_type.id),
                    "unit_label": "A-1-101",
                    "our_price": "100.00",
                    "order_number": "AZ-100",
                    "house_number": "A",
                    "floor_label": "1",
                    "apartment_number": "101",
                    "door_marking": "D-101",
                },
                {
                    "door_type_id": str(door_type.id),
                    "unit_label": "A-1-102",
                    "our_price": "100.00",
                    "order_number": "AZ-100",
                    "house_number": "A",
                    "floor_label": "1",
                    "apartment_number": "102",
                    "door_marking": "D-102",
                },
                {
                    "door_type_id": str(door_type.id),
                    "unit_label": "A-2-201",
                    "our_price": "100.00",
                    "order_number": "AZ-200",
                    "house_number": "A",
                    "floor_label": "2",
                    "apartment_number": "201",
                    "door_marking": "D-201",
                },
            ]
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 3

    details_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}?order_number=az-100"
    )
    assert details_resp.status_code == 200, details_resp.text
    details = details_resp.json()
    assert len(details["doors"]) == 2
    assert all(d["order_number"] == "AZ-100" for d in details["doors"])

    layout_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}/doors/layout?order_number=AZ-200"
    )
    assert layout_resp.status_code == 200, layout_resp.text
    layout = layout_resp.json()
    assert layout["total_doors"] == 1
    assert len(layout["buckets"]) == 1
    bucket = layout["buckets"][0]
    assert bucket["order_number"] == "AZ-200"
    assert bucket["total"] == 1


def test_projects_validation_returns_422(client_admin_real_uow):
    create_invalid_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects",
        json={"address": "Only address"},
    )
    assert create_invalid_resp.status_code == 422, create_invalid_resp.text

    project_id = _create_project(
        client_admin_real_uow,
        "Project Validation",
        "Validation address",
    )
    import_invalid_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import",
        json={"rows": []},
    )
    assert import_invalid_resp.status_code == 422, import_invalid_resp.text

    assign_invalid_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/doors/not-a-uuid/assign-installer",
        json={"installer_id": str(uuid.uuid4())},
    )
    assert assign_invalid_resp.status_code == 422, assign_invalid_resp.text

    invalid_phone_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects",
        json={
            "name": "Bad Phone Project",
            "address": "Validation address",
            "contact_phone": "abc",
        },
    )
    assert invalid_phone_resp.status_code == 422, invalid_phone_resp.text
    assert invalid_phone_resp.json()["error"]["code"] == "INVALID_PHONE"

    invalid_waze_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects",
        json={
            "name": "Bad Waze Project",
            "address": "Validation address",
            "address_waze_url": "ftp://bad-link",
        },
    )
    assert invalid_waze_resp.status_code == 422, invalid_waze_resp.text
    assert invalid_waze_resp.json()["error"]["code"] == "INVALID_WAZE_URL"


def test_projects_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/projects")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    layout_resp = client_installer.get(
        f"/api/v1/admin/projects/{uuid.uuid4()}/doors/layout"
    )
    assert layout_resp.status_code == 403, layout_resp.text
    assert layout_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    bulk_assign_resp = client_installer.post(
        "/api/v1/admin/projects/doors/bulk-assign-installer",
        json={"door_ids": [str(uuid.uuid4())], "installer_id": str(uuid.uuid4())},
    )
    assert bulk_assign_resp.status_code == 403, bulk_assign_resp.text
    assert bulk_assign_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_projects_multi_tenant_isolation(
    client_admin_real_uow, db_session, make_door_type, make_installer
):
    foreign_company_id = uuid.uuid4()
    foreign_project = ProjectORM(
        company_id=foreign_company_id,
        name="Foreign Project",
        address="Foreign Address",
        status=ProjectStatus.OK,
    )
    db_session.add(foreign_project)
    db_session.commit()
    db_session.refresh(foreign_project)

    local_door_type = make_door_type(name="Local Door Type")
    local_installer = make_installer(
        full_name="Local Installer MT",
        phone="+10000003002",
    )

    foreign_door_type = make_door_type(
        name="Foreign Door Type",
        company=foreign_company_id,
    )
    foreign_door = DoorORM(
        company_id=foreign_company_id,
        project_id=foreign_project.id,
        door_type_id=foreign_door_type.id,
        unit_label="F-01",
        our_price=Decimal("200.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(foreign_door)
    db_session.commit()
    db_session.refresh(foreign_door)

    try:
        get_resp = client_admin_real_uow.get(
            f"/api/v1/admin/projects/{foreign_project.id}"
        )
        assert get_resp.status_code == 404, get_resp.text

        import_resp = client_admin_real_uow.post(
            f"/api/v1/admin/projects/{foreign_project.id}/doors/import",
            json={
                "rows": [
                    {
                        "door_type_id": str(local_door_type.id),
                        "unit_label": "X-01",
                        "our_price": "50.00",
                    }
                ]
            },
        )
        assert import_resp.status_code == 404, import_resp.text

        assign_resp = client_admin_real_uow.post(
            f"/api/v1/admin/projects/doors/{foreign_door.id}/assign-installer",
            json={"installer_id": str(local_installer.id)},
        )
        assert assign_resp.status_code == 404, assign_resp.text

        bulk_assign_resp = client_admin_real_uow.post(
            "/api/v1/admin/projects/doors/bulk-assign-installer",
            json={"door_ids": [str(foreign_door.id)], "installer_id": str(local_installer.id)},
        )
        assert bulk_assign_resp.status_code == 404, bulk_assign_resp.text
    finally:
        db_session.rollback()
        db_session.execute(
            text("DELETE FROM doors WHERE id = :did"),
            {"did": foreign_door.id},
        )
        db_session.execute(
            text("DELETE FROM door_types WHERE id = :dtid"),
            {"dtid": foreign_door_type.id},
        )
        db_session.execute(
            text("DELETE FROM projects WHERE id = :pid"),
            {"pid": foreign_project.id},
        )
        db_session.commit()
