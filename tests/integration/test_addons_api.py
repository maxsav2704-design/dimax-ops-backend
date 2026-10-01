from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, require_installer
from app.main import create_app
from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM, ProjectAddonPlanORM
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


@pytest.fixture()
def addon_payroll_case(client_installer_addons, db_session, company_id, make_door_type):
    from types import SimpleNamespace

    client, installer_id = client_installer_addons
    project = _create_project(db_session, company_id=company_id, name="Addon payroll acceptance")
    addon = AddonTypeORM(company_id=company_id, name="Adjustment", unit="pcs", is_active=True)
    db_session.add(addon)
    db_session.flush()
    plan = ProjectAddonPlanORM(
        company_id=company_id, project_id=project.id, addon_type_id=addon.id,
        qty_planned=Decimal("3"), client_price=Decimal("20"), installer_price=Decimal("9.99"),
    )
    db_session.add_all([plan, DoorORM(
        company_id=company_id, project_id=project.id, door_type_id=make_door_type().id,
        unit_label="ADDON-101", our_price=Decimal("100"), installer_id=installer_id,
        status=DoorStatus.NOT_INSTALLED, is_locked=False,
    )])
    db_session.commit()
    return SimpleNamespace(client=client, project=project, addon=addon, plan=plan, installer_id=installer_id)


def _submit_addon(case, *, quantity="1.50", channel="sync", event_id="addon-financial-check"):
    body = {"addon_type_id": str(case.addon.id), "qty_done": quantity, "comment": "Test adjustment"}
    if channel == "direct":
        return case.client.post(f"/api/v1/installer/addons/projects/{case.project.id}/facts", json={
            **body, "client_event_id": event_id,
        })
    return case.client.post("/api/v1/installer/sync", json={
        "since_cursor": 0, "ack_cursor": 0, "device_id": "addon-financial-check",
        "events": [{"client_event_id": event_id, "type": "ADDON_FACT_CREATE",
                    "project_id": str(case.project.id), "payload": body}],
    })


@pytest.mark.parametrize("quantity", ["1.001", "NaN", "Infinity", "10000000000"])
def test_addon_sync_rejects_invalid_quantity_without_fact_or_earnings(addon_payroll_case, db_session, quantity):
    case = addon_payroll_case
    response = _submit_addon(case, quantity=quantity)
    assert response.status_code == 200, response.text
    ack = response.json()["acks"][0]
    assert ack["ok"] is False and ack["error"] == "CONFLICT_INVALID_TRANSITION", ack
    assert db_session.query(ProjectAddonFactORM).filter_by(project_id=case.project.id).count() == 0
    assert db_session.query(CompletedWorkORM).filter_by(project_id=case.project.id).count() == 0


@pytest.mark.parametrize("channel", ["direct", "sync"])
@pytest.mark.parametrize("quantity,rate", [("0.01", "0.01"), ("9999999999.99", "9.99")])
def test_addon_rejects_unrepresentable_payroll_amount(addon_payroll_case, db_session, channel, quantity, rate):
    case = addon_payroll_case
    case.plan.installer_price = Decimal(rate)
    db_session.commit()
    response = _submit_addon(case, channel=channel, quantity=quantity)
    if channel == "direct":
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    else:
        assert response.status_code == 200, response.text
        assert response.json()["acks"][0]["error"] == "CONFLICT_INVALID_TRANSITION"
    assert db_session.query(ProjectAddonFactORM).filter_by(project_id=case.project.id).count() == 0
    assert db_session.query(CompletedWorkORM).filter_by(project_id=case.project.id).count() == 0


@pytest.mark.parametrize("channel", ["direct", "sync"])
def test_addon_replay_keeps_original_rounded_rate_snapshot(addon_payroll_case, client_admin_real_uow, db_session, channel):
    case = addon_payroll_case
    first = _submit_addon(case, channel=channel)
    assert first.status_code == 200, first.text
    if channel == "sync":
        assert first.json()["acks"][0]["ok"] is True
    changed = client_admin_real_uow.put(f"/api/v1/admin/addons/projects/{case.project.id}/plan", json={
        "addon_type_id": str(case.addon.id), "qty_planned": "3", "client_price": "30", "installer_price": "25",
    })
    assert changed.status_code == 200, changed.text
    replay = _submit_addon(case, channel=channel)
    assert replay.status_code == 200, replay.text
    ack = replay.json()["acks"][0] if channel == "sync" else replay.json()
    assert ack["ok"] is True and ack["applied"] is False
    assert db_session.query(ProjectAddonFactORM).filter_by(project_id=case.project.id).count() == 1
    work = db_session.query(CompletedWorkORM).filter_by(project_id=case.project.id).one()
    assert work.quantity == Decimal("1.50") and work.rate_snapshot == Decimal("9.99")
    assert work.amount_snapshot == Decimal("14.99")


@pytest.mark.parametrize("channel", ["direct", "sync"])
def test_addon_direct_event_id_reuse_rejects_changed_payload(addon_payroll_case, db_session, channel):
    case = addon_payroll_case
    first = _submit_addon(case, channel="direct")
    assert first.status_code == 200, first.text
    changed = _submit_addon(case, channel=channel, quantity="2.50")
    if channel == "direct":
        assert changed.status_code == 409, changed.text
    else:
        assert changed.status_code == 200, changed.text
        assert changed.json()["acks"][0]["ok"] is False, changed.text
    assert db_session.query(ProjectAddonFactORM).filter_by(project_id=case.project.id).count() == 1
    assert db_session.query(CompletedWorkORM).filter_by(project_id=case.project.id).one().amount_snapshot == Decimal("14.99")


@pytest.mark.parametrize("quantities,total", [(["0.25"], "2.50"), (["1.50", "0.25"], "17.49")])
def test_addon_earnings_summary_preserves_fractional_type_quantity(addon_payroll_case, quantities, total):
    case = addon_payroll_case
    for index, quantity in enumerate(quantities):
        response = _submit_addon(case, quantity=quantity, event_id=f"fractional-summary-{index}")
        assert response.status_code == 200, response.text
        assert response.json()["acks"][0]["ok"] is True

    response = case.client.get("/api/v1/installer/earnings/summary?period=month")
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["jobs_count"] == len(quantities)
    assert len(summary["install_types"]) == 1
    group = summary["install_types"][0]
    assert group["code"] == f"addon:{case.addon.id}"
    assert isinstance(group["quantity"], (int, float))
    assert Decimal(str(group["quantity"])) == sum(map(Decimal, quantities))
    assert Decimal(group["amount"]) == Decimal(total)
    assert sum(Decimal(str(row["quantity"])) for row in summary["rows"]) == Decimal(str(group["quantity"]))


@pytest.mark.parametrize("concurrent_plan", [False, True])
def test_concurrent_addon_writes_preserve_one_fact_one_earning(addon_payroll_case, db_session, concurrent_plan):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import text
    from app.modules.addons.application.use_cases import AddonsUseCases
    from app.modules.addons.domain.enums import AddonFactSource
    from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

    case = addon_payroll_case
    company_id, project_id, addon_id, installer_id = (
        case.project.company_id, case.project.id, case.addon.id, case.installer_id,
    )
    if concurrent_plan:
        db_session.delete(case.plan)
        db_session.commit()
    barrier = Barrier(2)

    def write(plan=False):
        with SqlAlchemyUnitOfWork() as uow:
            uow.session.execute(text("SET LOCAL lock_timeout = '5s'"))
            barrier.wait(timeout=10)
            if plan:
                AddonsUseCases.admin_set_project_plan(
                    uow, company_id=company_id, project_id=project_id, addon_type_id=addon_id,
                    qty_planned=Decimal("3"), client_price=Decimal("20"), installer_price=Decimal("9.99"),
                )
                return "plan"
            fact = AddonsUseCases.installer_add_fact(
                uow, company_id=company_id, project_id=project_id, installer_id=installer_id,
                addon_type_id=addon_id, qty_done=Decimal("1.50"), comment="Concurrent acceptance",
                done_at=None, source=AddonFactSource.OFFLINE, client_event_id="concurrent-addon",
            )
            return str(fact.id) if fact else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write), executor.submit(write, concurrent_plan)]
        results = [future.result(timeout=20) for future in futures]
    if not concurrent_plan:
        assert results.count(None) == 1
    assert db_session.query(ProjectAddonFactORM).filter_by(project_id=project_id).count() == 1
    work = db_session.query(CompletedWorkORM).filter_by(project_id=project_id).one()
    assert work.amount_snapshot == Decimal("14.99") and work.rate_snapshot == Decimal("9.99")
