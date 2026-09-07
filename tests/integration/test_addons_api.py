from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, require_installer
from app.main import create_app
from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonPlanORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


@pytest.fixture()
def client_installer_addons(installer_user: CurrentUser, db_session):
    installer = InstallerORM(
        company_id=installer_user.company_id,
        full_name="Installer Addons",
        phone=f"+1999{uuid.uuid4().hex[:8]}",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.commit()
    db_session.refresh(installer)

    app = create_app()

    def _require_installer() -> CurrentUser:
        return installer_user

    def _get_current_installer_id() -> uuid.UUID:
        return installer.id

    app.dependency_overrides[require_installer] = _require_installer
    app.dependency_overrides[get_current_installer_id] = _get_current_installer_id

    with TestClient(app) as test_client:
        yield test_client, installer.id

    app.dependency_overrides.clear()


def _create_project(db_session, *, company_id: uuid.UUID, name: str) -> ProjectORM:
    row = ProjectORM(
        company_id=company_id,
        name=name,
        address=f"{name} address",
        status=ProjectStatus.OK,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_admin_addons_types_and_plan_flow(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Addons Plan {uuid.uuid4().hex[:8]}",
    )

    create_type_resp = client_admin_real_uow.post(
        "/api/v1/admin/addons/types",
        json={
            "name": "Foam",
            "unit": "pcs",
            "default_client_price": "25.00",
            "default_installer_price": "10.00",
        },
    )
    assert create_type_resp.status_code == 200, create_type_resp.text
    addon_type_id = create_type_resp.json()["id"]

    list_resp = client_admin_real_uow.get("/api/v1/admin/addons/types")
    assert list_resp.status_code == 200, list_resp.text
    listed_ids = {x["id"] for x in list_resp.json()["items"]}
    assert addon_type_id in listed_ids

    set_plan_resp = client_admin_real_uow.put(
        f"/api/v1/admin/addons/projects/{project.id}/plan",
        json={
            "addon_type_id": addon_type_id,
            "qty_planned": "3.00",
            "client_price": "30.00",
            "installer_price": "12.00",
        },
    )
    assert set_plan_resp.status_code == 200, set_plan_resp.text
    body = set_plan_resp.json()
    assert body["project_id"] == str(project.id)
    assert len(body["items"]) == 1
    assert body["items"][0]["addon_type_id"] == addon_type_id
    assert body["items"][0]["qty_planned"] == "3.00"
    assert body["items"][0]["addon_name"] == "Foam"

    post_plan_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project.id}/addons/plan",
        json={
            "addon_type_id": addon_type_id,
            "qty_planned": "4.00",
            "client_price": "35.00",
            "installer_price": "14.00",
            "notes": "Approved extra foam",
        },
    )
    assert post_plan_resp.status_code == 200, post_plan_resp.text
    post_body = post_plan_resp.json()
    assert len(post_body["items"]) == 1
    assert post_body["items"][0]["id"]
    assert post_body["items"][0]["addon_type_id"] == addon_type_id
    assert post_body["items"][0]["addon_name"] == "Foam"
    assert post_body["items"][0]["qty_planned"] == "4.00"
    assert post_body["items"][0]["notes"] == "Approved extra foam"

    get_plan_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project.id}/addons/plan"
    )
    assert get_plan_resp.status_code == 200, get_plan_resp.text
    get_plan_body = get_plan_resp.json()
    assert get_plan_body["items"][0]["addon_name"] == "Foam"
    assert get_plan_body["items"][0]["notes"] == "Approved extra foam"

    create_urgency_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project.id}/urgency-surcharges",
        json={
            "scope": "ORDER_NUMBER",
            "order_number": "ORD-7",
            "reason": "Urgent delivery window",
            "client_amount": "250.00",
            "installer_amount": "80.00",
            "effective_date": "2026-04-26",
            "notes": "Approved by client",
        },
    )
    assert create_urgency_resp.status_code == 200, create_urgency_resp.text
    urgency_body = create_urgency_resp.json()
    assert len(urgency_body["items"]) == 1
    assert urgency_body["items"][0]["scope"] == "ORDER_NUMBER"
    assert urgency_body["items"][0]["order_number"] == "ORD-7"
    assert urgency_body["items"][0]["client_amount"] == "250.00"
    assert urgency_body["items"][0]["installer_amount"] == "80.00"
    assert urgency_body["items"][0]["notes"] == "Approved by client"

    list_urgency_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project.id}/urgency-surcharges"
    )
    assert list_urgency_resp.status_code == 200, list_urgency_resp.text
    assert list_urgency_resp.json()["items"][0]["reason"] == "Urgent delivery window"


def test_admin_addons_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/addons/types")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_installer_addons_get_and_add_fact_flow(
    client_installer_addons,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id = client_installer_addons
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Installer Addons {uuid.uuid4().hex[:8]}",
    )
    door_type = make_door_type(name="Addons Door Type")
    db_session.add(
        DoorORM(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            unit_label="A-01",
            our_price=Decimal("100.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer_id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        )
    )
    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Seal",
        unit="pcs",
        default_client_price=Decimal("20.00"),
        default_installer_price=Decimal("9.00"),
        is_active=True,
        deleted_at=None,
    )
    db_session.add(addon_type)
    db_session.flush()
    db_session.add(
        ProjectAddonPlanORM(
            company_id=company_id,
            project_id=project.id,
            addon_type_id=addon_type.id,
            qty_planned=Decimal("2.00"),
            client_price=Decimal("20.00"),
            installer_price=Decimal("9.00"),
        )
    )
    db_session.commit()

    get_resp = client.get(f"/api/v1/installer/addons/projects/{project.id}")
    assert get_resp.status_code == 200, get_resp.text
    get_body = get_resp.json()
    assert get_body["project_id"] == str(project.id)
    assert len(get_body["plan"]) == 1
    assert "client_price" not in get_body["plan"][0]
    assert "installer_price" not in get_body["plan"][0]
    assert len(get_body["facts"]) == 0

    add_fact_resp = client.post(
        f"/api/v1/installer/addons/projects/{project.id}/facts",
        json={
            "addon_type_id": str(addon_type.id),
            "qty_done": "1.50",
            "comment": "done",
            "client_event_id": "evt-1",
        },
    )
    assert add_fact_resp.status_code == 200, add_fact_resp.text
    fact_body = add_fact_resp.json()
    assert fact_body["ok"] is True
    assert fact_body["applied"] is True
    assert fact_body["fact_id"] is not None

    duplicate_resp = client.post(
        f"/api/v1/installer/addons/projects/{project.id}/facts",
        json={
            "addon_type_id": str(addon_type.id),
            "qty_done": "1.50",
            "comment": "done",
            "client_event_id": "evt-1",
        },
    )
    assert duplicate_resp.status_code == 200, duplicate_resp.text
    duplicate_body = duplicate_resp.json()
    assert duplicate_body["ok"] is True
    assert duplicate_body["applied"] is False
    assert duplicate_body["fact_id"] is None

    completed_rows = (
        db_session.query(CompletedWorkORM)
        .filter(
            CompletedWorkORM.company_id == company_id,
            CompletedWorkORM.installer_id == installer_id,
            CompletedWorkORM.work_kind == "ADDON",
        )
        .all()
    )
    assert len(completed_rows) == 1
    assert completed_rows[0].addon_fact_id is not None
    assert completed_rows[0].door_id is None
    assert completed_rows[0].quantity == Decimal("1.50")
    assert completed_rows[0].rate_snapshot == Decimal("9.00")
    assert completed_rows[0].amount_snapshot == Decimal("13.50")

    earnings_resp = client.get("/api/v1/installer/earnings/summary?period=day")
    assert earnings_resp.status_code == 200, earnings_resp.text
    earnings_body = earnings_resp.json()
    assert earnings_body["total"] == "13.50"
    assert earnings_body["jobs_count"] == 1
    assert earnings_body["rows"][0]["install_type_label"] == "Seal"

    get_after_resp = client.get(f"/api/v1/installer/addons/projects/{project.id}")
    assert get_after_resp.status_code == 200, get_after_resp.text
    assert len(get_after_resp.json()["facts"]) == 1


def test_admin_addon_plan_reconciles_existing_installer_fact_into_earnings(
    client_installer_addons,
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id = client_installer_addons
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Late Addon Plan {uuid.uuid4().hex[:8]}",
    )
    door_type = make_door_type(name="Late Addon Door Type")
    db_session.add(
        DoorORM(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            unit_label="L-01",
            our_price=Decimal("100.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer_id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        )
    )
    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Late seal",
        unit="pcs",
        default_client_price=Decimal("20.00"),
        default_installer_price=Decimal("8.00"),
        is_active=True,
        deleted_at=None,
    )
    db_session.add(addon_type)
    db_session.commit()

    add_fact_resp = client.post(
        f"/api/v1/installer/addons/projects/{project.id}/facts",
        json={
            "addon_type_id": str(addon_type.id),
            "qty_done": "2.00",
            "comment": "done before plan",
            "client_event_id": "evt-late-plan",
        },
    )
    assert add_fact_resp.status_code == 200, add_fact_resp.text
    assert (
        db_session.query(CompletedWorkORM)
        .filter(
            CompletedWorkORM.company_id == company_id,
            CompletedWorkORM.installer_id == installer_id,
            CompletedWorkORM.work_kind == "ADDON",
        )
        .count()
        == 0
    )

    plan_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project.id}/addons/plan",
        json={
            "addon_type_id": str(addon_type.id),
            "qty_planned": "2.00",
            "client_price": "25.00",
            "installer_price": "8.00",
        },
    )
    assert plan_resp.status_code == 200, plan_resp.text

    completed = (
        db_session.query(CompletedWorkORM)
        .filter(
            CompletedWorkORM.company_id == company_id,
            CompletedWorkORM.installer_id == installer_id,
            CompletedWorkORM.work_kind == "ADDON",
        )
        .one()
    )
    assert completed.quantity == Decimal("2.00")
    assert completed.rate_snapshot == Decimal("8.00")
    assert completed.amount_snapshot == Decimal("16.00")


def test_installer_addons_forbidden_if_project_not_assigned(
    client_installer_addons,
    db_session,
    company_id,
):
    client, _installer_id = client_installer_addons
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"No Access {uuid.uuid4().hex[:8]}",
    )

    resp = client.get(f"/api/v1/installer/addons/projects/{project.id}")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_installer_addons_validation_and_not_found(
    client_installer_addons,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id = client_installer_addons
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Validation {uuid.uuid4().hex[:8]}",
    )
    door_type = make_door_type(name="Validation Door")
    db_session.add(
        DoorORM(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            unit_label="B-01",
            our_price=Decimal("80.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer_id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        )
    )
    db_session.commit()

    negative_qty_resp = client.post(
        f"/api/v1/installer/addons/projects/{project.id}/facts",
        json={
            "addon_type_id": str(uuid.uuid4()),
            "qty_done": "-1.00",
        },
    )
    assert negative_qty_resp.status_code == 422, negative_qty_resp.text
    assert negative_qty_resp.json()["error"]["code"] == "VALIDATION_ERROR"

    missing_type_resp = client.post(
        f"/api/v1/installer/addons/projects/{project.id}/facts",
        json={
            "addon_type_id": str(uuid.uuid4()),
            "qty_done": "1.00",
        },
    )
    assert missing_type_resp.status_code == 404, missing_type_resp.text
    assert missing_type_resp.json()["error"]["code"] == "NOT_FOUND"


def test_admin_addon_financial_fields_reject_invalid_decimals(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Addon Validation {uuid.uuid4().hex[:8]}",
    )

    invalid_type = client_admin_real_uow.post(
        "/api/v1/admin/addons/types",
        json={
            "name": "Invalid negative addon",
            "unit": "pcs",
            "default_client_price": "10.00",
            "default_installer_price": "-1.00",
        },
    )
    assert invalid_type.status_code == 422, invalid_type.text

    valid_type = client_admin_real_uow.post(
        "/api/v1/admin/addons/types",
        json={
            "name": "Validated addon",
            "unit": "pcs",
            "default_client_price": "10.00",
            "default_installer_price": "5.00",
        },
    )
    assert valid_type.status_code == 200, valid_type.text
    addon_type_id = valid_type.json()["id"]

    invalid_values = (
        {"qty_planned": "-1.00", "client_price": "10.00", "installer_price": "5.00"},
        {"qty_planned": "1.00", "client_price": "-0.01", "installer_price": "5.00"},
        {"qty_planned": "1.00", "client_price": "10.00", "installer_price": "-0.01"},
        {"qty_planned": "1.001", "client_price": "10.00", "installer_price": "5.00"},
    )
    for values in invalid_values:
        response = client_admin_real_uow.put(
            f"/api/v1/admin/addons/projects/{project.id}/plan",
            json={"addon_type_id": addon_type_id, **values},
        )
        assert response.status_code == 422, response.text

    assert (
        db_session.query(ProjectAddonPlanORM)
        .filter(ProjectAddonPlanORM.project_id == project.id)
        .count()
        == 0
    )