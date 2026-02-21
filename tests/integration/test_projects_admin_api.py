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
    project_id = _create_project(
        client_admin_real_uow,
        name="Project CRUD A",
        address="Main street 1",
    )

    details_resp = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details_resp.status_code == 200, details_resp.text
    details = details_resp.json()
    assert details["id"] == project_id
    assert details["name"] == "Project CRUD A"
    assert isinstance(details["doors"], list)
    assert isinstance(details["issues_open"], list)

    update_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/projects/{project_id}",
        json={"name": "Project CRUD B", "contact_name": "Manager"},
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

    list_resp = client_admin_real_uow.get("/api/v1/admin/projects")
    assert list_resp.status_code == 200, list_resp.text
    listed_ids = {x["id"] for x in list_resp.json()["items"]}
    assert project_id in listed_ids

    delete_resp = client_admin_real_uow.delete(f"/api/v1/admin/projects/{project_id}")
    assert delete_resp.status_code == 200, delete_resp.text
    assert delete_resp.json()["ok"] is True

    deleted_details_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}"
    )
    assert deleted_details_resp.status_code == 404, deleted_details_resp.text
    assert deleted_details_resp.json()["error"]["code"] == "NOT_FOUND"


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


def test_projects_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/projects")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


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
