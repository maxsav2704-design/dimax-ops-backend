from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.modules.addons.application.use_cases import AddonsUseCases
from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM, ProjectAddonPlanORM
from app.modules.doors.application.commands import AdminOverrideDoor, MarkDoorInstalled
from app.modules.doors.application.use_cases import DoorUseCases
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.application.admin_api_service import EarningsAdminApiService
from app.modules.earnings.application.factory_pricing import FactoryEarningsPricing
from app.modules.earnings.infrastructure.factory_price_models import FactoryEarningPriceORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.application.timeline_dto import ActivatePriceVersion
from app.modules.rates.application.timeline_service import FactoryPriceTimelineService
from app.modules.sync.infrastructure.models import SyncEventORM, SyncQueueItemORM
from app.shared.domain.errors import Conflict
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_price_timeline import confirmed, transition


@pytest.fixture()
def case(company_id, admin_user, installer_user, make_installer, make_door_type, db_session, client_installer):
    installer = make_installer()
    installer.user_id = installer_user.id
    door_type = make_door_type()
    project = ProjectORM(company_id=company_id, name="Factory earnings QA", address="QA", status="OK")
    addon = AddonTypeORM(company_id=company_id, name="Adjustment", unit="pcs", is_active=True)
    db_session.add_all([project, addon])
    db_session.flush()
    door = DoorORM(company_id=company_id, project_id=project.id, door_type_id=door_type.id,
        installer_id=installer.id, unit_label="QA-101", status=DoorStatus.IN_PROGRESS,
        version=0, our_price=Decimal("500"), installer_rate_snapshot=Decimal("999"), is_locked=False)
    plan = ProjectAddonPlanORM(company_id=company_id, project_id=project.id, addon_type_id=addon.id,
        qty_planned=Decimal("3"), client_price=Decimal("20"), installer_price=Decimal("999"))
    db_session.add_all([door, plan])
    db_session.commit()
    items = [{"kind": "DOOR", "target_id": door_type.id, "installer_price": "250"},
             {"kind": "ADDON", "target_id": addon.id, "installer_price": "9"}]
    return SimpleNamespace(company=company_id, actor=admin_user.id, installer=installer.id,
        project=project.id, door=door.id, door_type=door_type.id, addon=addon.id, plan=plan.id,
        items=items, client=client_installer)


def activate(case, *, expected=0, previous=None, door_price="250", addon_price="9"):
    items = [{**item, "installer_price": door_price if item["kind"] == "DOOR" else addon_price}
             for item in case.items]
    version = confirmed(case.company, case.actor, items, expected)
    return version, transition(case.company, case.actor, version, previous)


def submit(case, kind, channel, at=None, event_id=None, extra_payload=None):
    event_id = event_id or str(uuid4())
    payload = ({"door_id": str(case.door), "status": "INSTALLED"} if kind == "DOOR"
               else {"addon_type_id": str(case.addon), "qty_done": "1.50", "comment": "QA"})
    payload.update(extra_payload or {})
    if channel == "install":
        return case.client.post(f"/api/v1/installer/doors/{case.door}/install", json={})
    if channel == "status":
        return case.client.patch(f"/api/v1/installer/doors/{case.door}/status", json={"status": "INSTALLED"})
    if channel == "direct":
        return case.client.post(f"/api/v1/installer/addons/projects/{case.project}/facts", json={
            **payload, "client_event_id": event_id, **({"done_at": at.isoformat()} if at else {}),
        })
    operation = "DOOR_SET_STATUS" if kind == "DOOR" else "ADDON_FACT_CREATE"
    time = {"happened_at": at.isoformat()} if at else {}
    if channel == "sync":
        return case.client.post("/api/v1/installer/sync", json={"device_id": "factory-qa", "events": [{
            "client_event_id": event_id, "type": operation, "project_id": str(case.project),
            "payload": payload, **time,
        }]})
    return case.client.post("/api/v1/installer/sync-queue/batch", json={"device_id": "factory-qa", "items": [{
        "id": event_id, "entity_type": "door" if kind == "DOOR" else "addon_fact",
        "entity_id": str(case.door) if kind == "DOOR" else event_id,
        "operation_type": operation, "project_id": str(case.project), "base_version": 0,
        "payload": payload, **time,
    }]})


def assert_applied(response, channel):
    assert response.status_code == 200, response.text
    if channel == "sync":
        assert response.json()["acks"][0]["ok"] is True, response.text
    elif channel == "batch":
        assert response.json()["results"][0]["status"] == "APPLIED", response.text


def earning(db_session, case):
    db_session.expire_all()
    work = db_session.scalars(select(CompletedWorkORM).where(CompletedWorkORM.company_id == case.company)).one()
    return work, db_session.get(FactoryEarningPriceORM, work.id)


@pytest.mark.parametrize("kind,channel", [("DOOR", "install"), ("DOOR", "status"),
    ("DOOR", "sync"), ("DOOR", "batch"), ("ADDON", "direct"), ("ADDON", "sync"), ("ADDON", "batch")])
def test_all_ingress_paths_use_factory_price_not_legacy_snapshot(case, db_session, kind, channel):
    version, activation = activate(case)
    assert_applied(submit(case, kind, channel, activation.effective_from), channel)
    work, proof = earning(db_session, case)
    assert work.amount_snapshot == (Decimal("250") if kind == "DOOR" else Decimal("13.50"))
    assert proof.price_list_id == version.id and proof.activation_id == activation.id
    assert proof.selection == "AT_EXECUTION" and len(proof.snapshot_hash) == 64
    assert proof.confirmed_rate == work.rate_snapshot and proof.performed_at == work.completed_at


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
@pytest.mark.parametrize("legacy", [False, True])
def test_late_upload_and_retry_retain_work_without_unproven_historic_earning(case, db_session, kind, channel, legacy):
    v1, a1 = activate(case)
    at = a1.effective_from - timedelta(days=2) if legacy else a1.effective_from
    activate(case, expected=1, previous=v1.id, door_price="300", addon_price="12")
    event_id = str(uuid4())
    for _ in range(2):
        response = submit(case, kind, channel, at, event_id)
        assert response.status_code == 200, response.text
        result = response.json()["acks" if channel == "sync" else "results"][0]
        assert result["error" if channel == "sync" else "conflict_code"] == "CONFLICT_FACTORY_PRICE"
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    model = SyncEventORM if channel == "sync" else SyncQueueItemORM
    row = db_session.query(model).filter_by(company_id=case.company).one()
    assert row.client_happened_at == at and row.payload


@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_legacy_review_proposes_first_confirmed_not_first_activated(case, db_session, client_admin_real_uow, channel):
    at = utcnow()
    v1 = confirmed(case.company, case.actor, case.items)
    activate(case, expected=1, door_price="300", addon_price="12")
    submit(case, "DOOR", channel, at, extra_payload={"base_version": 0})
    model = SyncEventORM if channel == "sync" else SyncQueueItemORM
    row = db_session.query(model).filter_by(company_id=case.company).one()
    source = "sync_event" if channel == "sync" else "sync_queue"
    review = client_admin_real_uow.get(f"/api/v1/admin/sync/price-conflicts/{source}/{row.id}").json()
    assert review["requires_execution_evidence"] is True
    assert review["applicable_quote"]["price_list_id"] == str(v1.id)
    assert Decimal(review["preview_amount"]) == Decimal("250")
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_missing_first_price_retains_failed_command_without_fallback(case, db_session, kind, channel, make_door_type):
    confirmed(case.company, case.actor, case.items)
    if kind == "DOOR":
        target = make_door_type(name="Later type").id
        db_session.get(DoorORM, case.door).door_type_id = target
        case.door_type = target
    else:
        addon = AddonTypeORM(company_id=case.company, name="Later addon", unit="pcs")
        db_session.add(addon)
        db_session.flush()
        target = addon.id
        case.addon = target
    db_session.commit()
    case.items.append({"kind": kind, "target_id": target, "installer_price": "500"})
    activate(case, expected=1)
    at, event_id = utcnow() - timedelta(days=2), str(uuid4())
    response = submit(case, kind, channel, at, event_id)
    assert response.status_code == 200, response.text
    result = response.json()["acks" if channel == "sync" else "results"][0]
    assert (result["ok"] is False if channel == "sync" else result["status"] == "CONFLICT"), response.text
    db_session.expire_all()
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(ProjectAddonFactORM).filter_by(company_id=case.company).count() == 0
    assert db_session.get(DoorORM, case.door).status == DoorStatus.IN_PROGRESS
    if channel == "sync":
        queued = db_session.query(SyncEventORM).filter_by(company_id=case.company, client_event_id=event_id).one()
    else:
        queued = db_session.get(SyncQueueItemORM, UUID(event_id))
    assert queued.client_happened_at == at
    assert queued.payload and queued.project_id == case.project


def test_addon_price_comes_from_the_factory_list_not_the_plan_price(case, db_session):
    activate(case)
    db_session.get(ProjectAddonPlanORM, case.plan).installer_price = Decimal("0")
    db_session.commit()
    assert_applied(submit(case, "ADDON", "direct"), "direct")
    assert earning(db_session, case)[0].amount_snapshot == Decimal("13.50")


@pytest.mark.parametrize("channel", ["direct", "sync"])
def test_addon_fact_without_office_plan_is_refused(case, db_session, channel):
    # Product rule: the office plans extra work; an unplanned fact is never paid.
    activate(case)
    db_session.delete(db_session.get(ProjectAddonPlanORM, case.plan))
    db_session.commit()
    response = submit(case, "ADDON", channel)
    if channel == "direct":
        assert response.status_code == 422, response.text
    else:
        assert response.status_code == 200, response.text
        assert response.json()["acks"][0]["ok"] is False, response.text
    db_session.expire_all()
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(ProjectAddonFactORM).filter_by(company_id=case.company).count() == 0


def test_uploaded_unpaid_fact_is_not_repriced_by_plan_edit_after_cutover(case, db_session):
    db_session.get(ProjectAddonPlanORM, case.plan).installer_price = 0
    db_session.commit()
    assert_applied(submit(case, "ADDON", "direct"), "direct")
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    activate(case)
    with SqlAlchemyUnitOfWork() as uow:
        AddonsUseCases.admin_set_project_plan(uow, company_id=case.company, project_id=case.project,
            addon_type_id=case.addon, qty_planned=Decimal("3"), client_price=Decimal("20"), installer_price=None)
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


def test_direct_backdating_cannot_claim_legacy_queue_exception(case, db_session):
    activate(case)
    response = submit(case, "ADDON", "direct", utcnow() - timedelta(days=2))
    assert response.status_code == 409, response.text
    assert db_session.query(ProjectAddonFactORM).filter_by(company_id=case.company).count() == 0


def test_reversal_and_admin_replay_preserve_original_proof(case, db_session, make_reason):
    v1, _ = activate(case)
    with SqlAlchemyUnitOfWork() as uow:
        DoorUseCases.admin_override(uow, AdminOverrideDoor(case.company, case.actor, case.door, "INSTALLED"), actor_role="ADMIN")
    original, proof = earning(db_session, case)
    original_id, original_hash = original.id, proof.snapshot_hash
    activate(case, expected=1, previous=v1.id, door_price="300")
    with SqlAlchemyUnitOfWork() as uow:
        DoorUseCases.admin_override(uow, AdminOverrideDoor(case.company, case.actor, case.door, "INSTALLED"), actor_role="ADMIN")
    assert earning(db_session, case)[0].id == original_id
    reason = make_reason()
    with SqlAlchemyUnitOfWork() as uow:
        DoorUseCases.admin_override(uow, AdminOverrideDoor(case.company, case.actor, case.door, "NOT_INSTALLED",
            reason_id=reason.id, override_reason="QA cancellation"), actor_role="ADMIN")
    db_session.expire_all()
    reversal = db_session.query(CompletedWorkORM).filter_by(company_id=case.company, entry_type="REVERSAL").one()
    assert reversal.amount_snapshot == -250 and reversal.correction_ref_id == original_id
    reversal_proof = db_session.get(FactoryEarningPriceORM, reversal.id)
    assert reversal_proof.price_list_id == v1.id and reversal_proof.snapshot_hash == original_hash
    with SqlAlchemyUnitOfWork() as uow:
        DoorUseCases.admin_override(uow, AdminOverrideDoor(case.company, case.actor, case.door, "INSTALLED"), actor_role="ADMIN")
    amounts = db_session.scalars(select(CompletedWorkORM.amount_snapshot).where(CompletedWorkORM.company_id == case.company)).all()
    assert sorted(amounts) == [Decimal("-250"), Decimal("250"), Decimal("300")]


def test_manual_correction_is_blocked_and_admin_ledger_explains_price(case, db_session):
    version, _ = activate(case)
    assert_applied(submit(case, "DOOR", "install"), "install")
    original, _ = earning(db_session, case)
    with pytest.raises(Conflict, match="manual rate"):
        with SqlAlchemyUnitOfWork() as uow:
            EarningsAdminApiService.create_correction(uow, company_id=case.company, actor_user_id=case.actor,
                completed_work_id=original.id, rate_snapshot=Decimal("900"), reason="QA")
    with SqlAlchemyUnitOfWork() as uow:
        result = EarningsAdminApiService.list_ledger(uow, company_id=case.company, installer_id=None,
            project_id=None, entry_type=None, work_kind=None, date_from=None, date_to=None, limit=50, offset=0)
    assert result.total == 1 and not result.items[0].can_correct
    assert result.items[0].factory_price.price_list_id == version.id
    assert result.items[0].factory_price.confirmed_rate == Decimal("250")


def test_nonconfirmed_installer_surcharge_cannot_modify_factory_rate(case, db_session):
    activate(case)
    door = db_session.get(DoorORM, case.door)
    door.apply_surcharge_to_installer, door.surcharge_pct = True, Decimal("150")
    db_session.commit()
    response = submit(case, "DOOR", "install")
    assert response.status_code == 409, response.text
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    db_session.refresh(door)
    assert door.status == DoorStatus.IN_PROGRESS


def test_price_evidence_cannot_cross_company_boundary(case, db_session):
    activate(case)
    assert_applied(submit(case, "DOOR", "install"), "install")
    _, proof = earning(db_session, case)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            proof.company_id = uuid4()
            db_session.flush()
    db_session.refresh(proof)
    assert proof.company_id == case.company


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_offline_missing_execution_time_is_not_priced_at_upload(case, db_session, kind, channel):
    activate(case)
    response = submit(case, kind, channel)
    assert response.status_code == 200, response.text
    result = response.json()["acks" if channel == "sync" else "results"][0]
    assert (result["ok"] is False if channel == "sync" else result["status"] == "CONFLICT"), response.text
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


def test_completion_and_price_amendment_serialize_without_repricing(case, db_session):
    v1, a1 = activate(case)
    v2 = confirmed(case.company, case.actor, [{**item, "installer_price": "400"} for item in case.items], 1)
    barrier = Barrier(2)
    def execute(complete):
        barrier.wait(timeout=15)
        with SqlAlchemyUnitOfWork() as uow:
            uow.session.execute(text("SET LOCAL lock_timeout = '10s'"))
            if complete:
                DoorUseCases.mark_installed(uow, MarkDoorInstalled(case.company, case.actor, case.door,
                    happened_at=a1.effective_from))
            else:
                FactoryPriceTimelineService.activate(uow, company_id=case.company, actor_user_id=case.actor,
                    price_list_id=v2.id, body=ActivatePriceVersion(request_id=uuid4(),
                        expected_active_price_list_id=v1.id, reason="QA concurrent amendment", reviewed_transition=True))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(execute, [True, False]))
    work, proof = earning(db_session, case)
    assert work.amount_snapshot == 250 and proof.price_list_id == v1.id


def test_evidence_failure_rolls_back_door_and_earning(case, db_session, monkeypatch):
    activate(case)
    attach = FactoryEarningsPricing.attach
    def fail_after_evidence(uow, work, quote):
        attach(uow, work, quote)
        raise Conflict("QA failure after evidence flush")
    monkeypatch.setattr(FactoryEarningsPricing, "attach", staticmethod(fail_after_evidence))
    response = submit(case, "DOOR", "install")
    assert response.status_code == 409, response.text
    db_session.expire_all()
    assert db_session.get(DoorORM, case.door).status == DoorStatus.IN_PROGRESS
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(FactoryEarningPriceORM).filter_by(company_id=case.company).count() == 0
