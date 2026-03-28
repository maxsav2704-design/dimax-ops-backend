from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import text

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


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
    assert details["address_street"] == "Main street"
    assert details["address_city"] == "Ashdod"
    assert details["waze_deep_link"] == "https://waze.com/ul?ll=31.801,34.643&navigate=yes"
    assert details["whatsapp_deep_link"] is not None
    assert "Добрый+день%2C+по+проекту+Project+CRUD+A+%28PRJ-CRUD-A%29" in details["whatsapp_deep_link"]
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
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    layout_resp = client_installer.get(
        f"/api/v1/admin/projects/{uuid.uuid4()}/doors/layout"
    )
    assert layout_resp.status_code == 403, layout_resp.text
    assert layout_resp.json()["error"]["code"] == "FORBIDDEN"


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
