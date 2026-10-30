"""Stage earnings (0090, step 4): factory-confirmed rates per door type and stage, ledger rows valued from stage
execution facts, the money gap shown when a rate is missing, visibility and offline data for stage installers."""
import runpy
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError as SchemaError
from sqlalchemy import delete, func, select, text

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import get_uow, require_installer
from app.core.config import settings
from app.main import create_app
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.doors.infrastructure.stage_models import (
    DoorStageAssignmentORM, DoorStageFactORM, DoorTypeStagePlanItemORM, DoorTypeStagePlanORM, DoorWorkPlanORM,
    WorkStageDefinitionORM,
)
from app.modules.earnings.infrastructure.factory_price_models import FactoryEarningPriceORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.rates.application.price_list_dto import CreatePriceList
from app.modules.rates.application.reconciliation_service import FactoryPriceReconciliationService
from app.modules.rates.application.timeline_service import FactoryPriceTimelineService as Timeline, MissingFactoryPrice
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.modules.rates.infrastructure.price_list_models import FactoryPriceListItemORM
from app.modules.sync.infrastructure.models import SyncChangeLogORM
from app.shared.domain.errors import ValidationError
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from fastapi.testclient import TestClient
from tests.conftest import TestSessionLocal, TestUnitOfWork
from test_factory_price_timeline import confirmed, transition
from test_work_stages import ADMIN, catalog, crew, owner, planned_door  # noqa: F401  (fixtures)

PRICE_WORDS = ("price", "rate", "amount", "earn")
# The status of an earning (recorded / no rate / pricing inactive) and its id carry no money; everything else must not.
STATUS_KEYS = {"earning_status", "earning_id"}


@pytest.fixture(autouse=True)
def stages_enabled(monkeypatch, db_session, company_id):
    monkeypatch.setattr(settings, "WORK_STAGES_ENABLED", True)
    yield
    db_session.rollback()
    db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))
    db_session.execute(delete(CompletedWorkORM).where(CompletedWorkORM.company_id == company_id,
                                                      CompletedWorkORM.work_kind == "STAGE"))
    for model in (DoorStageFactORM, DoorStageAssignmentORM, DoorWorkPlanORM, DoorTypeStagePlanItemORM,
                  DoorTypeStagePlanORM):
        db_session.execute(delete(model).where(model.company_id == company_id))
    db_session.execute(delete(FactoryPriceListItemORM).where(FactoryPriceListItemORM.company_id == company_id,
                                                             FactoryPriceListItemORM.kind == "STAGE"))
    db_session.execute(delete(WorkStageDefinitionORM).where(WorkStageDefinitionORM.company_id == company_id))
    db_session.commit()


def client_for(installer_row, installer_user):
    app = create_app()
    app.dependency_overrides[get_uow] = lambda: TestUnitOfWork(TestSessionLocal)
    app.dependency_overrides[require_installer] = lambda: installer_user
    app.dependency_overrides[get_current_installer_id] = lambda: installer_row.id
    return TestClient(app)


def stage_prices(company_id, actor, door_type_id, rates: dict, *, door_price="250.00"):
    """One confirmed and effective version: the door type's full price plus the given stage rates."""
    items = [{"kind": "DOOR", "target_id": door_type_id, "installer_price": door_price}]
    items += [{"kind": "STAGE", "target_id": door_type_id, "stage_code": code, "installer_price": rate}
              for code, rate in rates.items()]
    version = confirmed(company_id, actor, items)
    return version, transition(company_id, actor, version)


def no_price_words(value) -> bool:
    if isinstance(value, dict):
        return all((str(key) in STATUS_KEYS or not any(word in str(key).lower() for word in PRICE_WORDS))
                   and no_price_words(item) for key, item in value.items())
    if isinstance(value, list):
        return all(no_price_words(item) for item in value)
    return True


def stage_rows(db_session, door_id):
    db_session.expire_all()
    return db_session.scalars(select(CompletedWorkORM).where(CompletedWorkORM.door_id == door_id)
                              .order_by(CompletedWorkORM.completed_at)).all()


# ---- price list ------------------------------------------------------------------------------------------------

def test_stage_lines_need_a_known_stage_and_keep_door_lines_byte_identical(owner, db_session, company_id, admin_user,
                                                                            make_door_type, catalog, monkeypatch):
    door, _ = planned_door(owner, db_session, company_id, make_door_type, catalog)
    door_type = door.door_type_id
    line = {"kind": "STAGE", "target_id": str(door_type), "stage_code": "frame", "installer_price": "100.00"}
    base = {"request_id": str(uuid.uuid4()), "expected_latest_version": 0, "reason": "r", "agreement_reference": "a"}
    for items in (
        [{**line, "stage_code": None}],                                        # STAGE without its stage
        [{"kind": "DOOR", "target_id": str(door_type), "stage_code": "FRAME", "installer_price": "1"}],  # DOOR with a stage
        [line, {**line, "stage_code": "FRAME"}],                               # same stage twice (case-insensitive)
    ):
        with pytest.raises(SchemaError):
            CreatePriceList(**base, items=items)
    assert CreatePriceList(**base, items=[line]).items[0].stage_code == "FRAME"
    unknown = owner.post(f"{ADMIN}/price-lists", json={**base, "items": [{**line, "stage_code": "GLAZING"}]})
    assert unknown.status_code == 422 and "GLAZING" in unknown.text
    monkeypatch.setattr(settings, "WORK_STAGES_ENABLED", False)
    assert owner.post(f"{ADMIN}/price-lists", json={**base, "items": [line]}).status_code == 422
    monkeypatch.setattr(settings, "WORK_STAGES_ENABLED", True)

    version, activation = stage_prices(company_id, admin_user.id, door_type, {"FRAME": "100.00", "LEAF": "150.00"})
    detail = owner.get(f"{ADMIN}/price-lists/{version.id}").json()
    stage_lines = {item["stage_code"]: item for item in detail["items"] if item["kind"] == "STAGE"}
    assert stage_lines["FRAME"]["name"] == "Staged entrance: Frame" and stage_lines["FRAME"]["unit"] == "pcs"
    assert stage_lines["LEAF"]["installer_price"] == "150.00"
    assert [item for item in detail["items"] if item["kind"] == "DOOR"][0]["stage_code"] is None
    # The factory's signed snapshot: DOOR lines keep exactly the five keys hashed before 0090.
    receipt = db_session.scalar(select(FactoryPriceApprovalORM).where(FactoryPriceApprovalORM.price_list_id == version.id))
    by_kind = {}
    for item in receipt.snapshot["items"]:
        by_kind.setdefault(item["kind"], []).append(item)
    assert set(by_kind["DOOR"][0]) == {"kind", "target_id", "name", "unit", "installer_price"}
    assert {item["stage_code"] for item in by_kind["STAGE"]} == {"FRAME", "LEAF"}
    assert set(by_kind["STAGE"][0]) == {"kind", "target_id", "name", "unit", "installer_price", "stage_code"}

    now = datetime.now(timezone.utc)
    with SqlAlchemyUnitOfWork() as uow:
        quote = Timeline.quote(uow, company_id=company_id, kind="STAGE", target_id=door_type, stage_code="LEAF", performed_at=now)
        assert quote.rate == Decimal("150.00") and quote.amount(Decimal("1")) == Decimal("150.00")
        assert quote.stage_code == "LEAF" and quote.activation_id == activation.id
        with pytest.raises(MissingFactoryPrice):
            Timeline.quote(uow, company_id=company_id, kind="STAGE", target_id=door_type, stage_code="FINISH", performed_at=now)
        with pytest.raises(ValidationError):
            Timeline.quote(uow, company_id=company_id, kind="STAGE", target_id=door_type, performed_at=now)
        with pytest.raises(ValidationError):
            Timeline.quote(uow, company_id=company_id, kind="DOOR", target_id=door_type, stage_code="FRAME", performed_at=now)
        # Devices only cache door and addon prices; the planned optional stage without a rate is a review note.
        assert {item.kind for item in Timeline.installer_snapshot(uow, company_id=company_id).items} == {"DOOR"}
        check = FactoryPriceReconciliationService.get(uow, company_id=company_id, price_list_id=version.id, limit=1,
                                                      offset=0, issues_only=False, kind=None).application_check
        assert not check.blockers
        assert {(issue.code, issue.count) for issue in check.review} >= {("MISSING_STAGE_PRICES", 1)}
    state = owner.get(f"{ADMIN}/price-lists/state").json()
    assert state["mode"] == "FACTORY" and {item["kind"] for item in state["active_price"]["items"]} == {"DOOR"}


# ---- valuation --------------------------------------------------------------------------------------------------

def test_stage_facts_are_valued_at_the_confirmed_stage_rate(owner, crew, db_session, company_id, admin_user,
                                                            make_door_type, catalog, monkeypatch):
    client_a, a, b = crew
    door, _ = planned_door(owner, db_session, company_id, make_door_type, catalog)
    version, _ = stage_prices(company_id, admin_user.id, door.door_type_id, {"FRAME": "100.00", "LEAF": "150.00"})
    stages = f"{ADMIN}/doors/{door.id}/stages"
    assert owner.post(f"{stages}/FRAME/assign", json={"installer_id": str(a.id)}).status_code == 200
    assert owner.post(f"{stages}/LEAF/assign", json={"installer_id": str(b.id)}).status_code == 200

    request_id = str(uuid.uuid4())
    done = client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete", json={"request_id": request_id})
    assert done.status_code == 200, done.text
    assert done.json()["earning_status"] == "RECORDED" and not done.json()["door_installed"]
    assert no_price_words(done.json())
    rows = stage_rows(db_session, door.id)
    assert len(rows) == 1
    frame = rows[0]
    fact = db_session.scalar(select(DoorStageFactORM).where(DoorStageFactORM.door_id == door.id, DoorStageFactORM.stage_code == "FRAME"))
    assert (frame.work_kind, frame.entry_type, frame.installer_id, frame.stage_fact_id, frame.door_id) == ("STAGE", "ORIGINAL", a.id, fact.id, door.id)
    assert (frame.quantity, frame.rate_snapshot, frame.amount_snapshot) == (Decimal("1.00"), Decimal("100.00"), Decimal("100.00"))
    assert frame.completed_at == fact.happened_at and frame.project_id == door.project_id
    proof = db_session.get(FactoryEarningPriceORM, frame.id)
    stage_item = db_session.scalar(select(FactoryPriceListItemORM).where(FactoryPriceListItemORM.price_list_id == version.id,
                                                                         FactoryPriceListItemORM.stage_code == "FRAME"))
    assert proof.price_list_item_id == stage_item.id and proof.confirmed_rate == Decimal("100.00") and proof.selection == "AT_EXECUTION"
    # Replay of the same request: no second fact, no second earning.
    replay = client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete", json={"request_id": request_id}).json()
    assert replay["applied"] is False and replay["earning_status"] == "RECORDED"
    assert len(stage_rows(db_session, door.id)) == 1

    # The office records B's LEAF: the door is installed by stages, each installer paid their own stage, no full-door earning.
    done = owner.post(f"{stages}/LEAF/complete", json={"installer_id": str(b.id)})
    assert done.status_code == 200, done.text
    assert done.json()["door_installed"] and done.json()["earning_status"] == "RECORDED"
    rows = stage_rows(db_session, door.id)
    assert [(r.work_kind, r.installer_id, r.amount_snapshot) for r in rows] == [("STAGE", a.id, Decimal("100.00")), ("STAGE", b.id, Decimal("150.00"))]
    assert db_session.get(DoorORM, door.id).status == DoorStatus.INSTALLED
    view = owner.get(stages).json()
    assert {s["stage_code"]: (s["earning_status"], s["earning_id"] is not None) for s in view["stages"]} == {
        "FRAME": ("RECORDED", True), "LEAF": ("RECORDED", True), "FINISH": (None, False)}
    assert no_price_words(view)

    # Installer A sees their stage in the earnings summary, labelled by door type and stage, at the stage rate.
    summary = client_a.get("/api/v1/installer/earnings/summary", params={"period": "day"}).json()
    mine = [row for row in summary["rows"] if row["install_type_code"].startswith("stage:")]
    assert len(mine) == 1 and Decimal(str(mine[0]["amount"])) == Decimal("100.00")
    assert mine[0]["install_type_label"] == "Staged entrance: Frame" and mine[0]["door_label"] == "S-1"
    assert Decimal(str(summary["total"])) == Decimal("100.00")

    # Admin ledger and CSV: STAGE rows carry the stage, explain the price and cannot be corrected by hand.
    ledger = owner.get(f"{ADMIN}/earnings/ledger", params={"work_kind": "STAGE", "project_id": str(door.project_id)}).json()
    assert {(item["stage_code"], item["can_correct"], item["factory_price"] is not None) for item in ledger["items"]} == {
        ("FRAME", False, True), ("LEAF", False, True)}
    assert all(item["stage_fact_id"] and item["door_label"] == "S-1" for item in ledger["items"])
    csv_text = owner.get(f"{ADMIN}/earnings/ledger/export", params={"work_kind": "STAGE", "project_id": str(door.project_id)}).text
    header = csv_text.splitlines()[0].split(",")
    assert header[-2:] == ["stage_fact_id", "stage_code"] and ",FRAME" in csv_text and ",LEAF" in csv_text
    assert owner.get(f"{ADMIN}/earnings/ledger", params={"work_kind": "DOOR", "project_id": str(door.project_id)}).json()["total"] == 0
    correction = owner.post(f"{ADMIN}/earnings/corrections", json={"completed_work_id": str(frame.id), "rate_snapshot": "1.00", "reason": "x"})
    assert correction.status_code == 409, correction.text
    # A staged door cannot be flipped back by override: its facts and earnings are immutable (redo is step 5).
    override = owner.post(f"{ADMIN}/doors/{door.id}/override", json={"new_status": "NOT_INSTALLED", "override_reason": "test",
                                                                     "reason_id": str(uuid.uuid4())})
    assert override.status_code == 409, override.text
    assert len(stage_rows(db_session, door.id)) == 2
    # The database refuses to lose stage earnings on downgrade.
    downgrade = runpy.run_path("alembic/versions/0090_stage_earnings.py")["downgrade"]
    monkeypatch.setitem(downgrade.__globals__, "op", Operations(MigrationContext.configure(db_session.connection())))
    with pytest.raises(RuntimeError, match="stage earnings"):
        downgrade()
    db_session.rollback()


def test_missing_stage_rate_keeps_the_fact_and_shows_the_gap(owner, crew, db_session, company_id, admin_user,
                                                            make_door_type, catalog):
    client_a, a, b = crew
    door, _ = planned_door(owner, db_session, company_id, make_door_type, catalog)
    stage_prices(company_id, admin_user.id, door.door_type_id, {"FRAME": "100.00"})
    stages = f"{ADMIN}/doors/{door.id}/stages"
    assert owner.post(f"{stages}/FRAME/assign", json={"installer_id": str(a.id)}).status_code == 200
    assert owner.post(f"{stages}/LEAF/assign", json={"installer_id": str(b.id)}).status_code == 200
    assert client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete", json={}).json()["earning_status"] == "RECORDED"
    done = owner.post(f"{stages}/LEAF/complete", json={"installer_id": str(b.id)})
    assert done.status_code == 200, done.text
    # The fact is proof of work and installs the door; the missing rate is a visible gap, never a guessed price.
    assert done.json()["door_installed"] and done.json()["earning_status"] == "NO_RATE"
    rows = stage_rows(db_session, door.id)
    assert [(r.work_kind, r.installer_id) for r in rows] == [("STAGE", a.id)]
    view = owner.get(stages).json()
    assert {s["stage_code"]: s["earning_status"] for s in view["stages"]} == {"FRAME": "RECORDED", "LEAF": "NO_RATE", "FINISH": None}
    audits = db_session.scalars(select(AuditLogORM).where(AuditLogORM.company_id == company_id, AuditLogORM.entity_id == door.id,
                                                          AuditLogORM.action == "DOOR_STAGE_COMPLETE")).all()
    assert {(row.after["stage_code"], row.after["earning_status"], row.after["creates_earning"]) for row in audits} == {
        ("FRAME", "RECORDED", True), ("LEAF", "NO_RATE", False)}
    assert db_session.get(DoorORM, door.id).status == DoorStatus.INSTALLED


def test_without_factory_pricing_stage_facts_stay_unpriced(owner, crew, db_session, company_id, make_door_type, catalog):
    client_a, a, _ = crew
    door, _ = planned_door(owner, db_session, company_id, make_door_type, catalog)
    assert owner.post(f"{ADMIN}/doors/{door.id}/stages/FRAME/assign", json={"installer_id": str(a.id)}).status_code == 200
    done = client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete", json={})
    assert done.status_code == 200 and done.json()["earning_status"] == "PRICING_INACTIVE"
    assert stage_rows(db_session, door.id) == []
    assert [s["earning_status"] for s in owner.get(f"{ADMIN}/doors/{door.id}/stages").json()["stages"]] == ["PRICING_INACTIVE", None, None]


# ---- visibility and offline data -----------------------------------------------------------------------------

def test_stage_installer_sees_the_door_and_receives_stage_changes(owner, crew, db_session, company_id, installer_user,
                                                                  make_door_type, catalog):
    client_a, a, b = crew
    client_b = client_for(b, installer_user)
    door, plan = planned_door(owner, db_session, company_id, make_door_type, catalog)   # nobody holds the door itself
    stages = f"{ADMIN}/doors/{door.id}/stages"
    assert owner.post(f"{stages}/FRAME/assign", json={"installer_id": str(a.id)}).status_code == 200
    assert owner.post(f"{stages}/LEAF/assign", json={"installer_id": str(b.id)}).status_code == 200

    # B holds no door of this project, only the LEAF stage: the cold snapshot still brings the door and its stages.
    cold = client_b.post("/api/v1/installer/sync", json={"since_cursor": 0, "device_id": "b-phone"})
    assert cold.status_code == 200, cold.text
    snapshot = cold.json()["snapshot"]
    assert snapshot is not None and [d["id"] for d in snapshot["doors"]] == [str(door.id)]
    assert [p["id"] for p in snapshot["projects"]] == [str(door.project_id)]
    assert len(snapshot["door_stages"]) == 1
    entry = snapshot["door_stages"][0]
    assert entry["door_id"] == str(door.id) and entry["plan_version"] == plan["version"]
    assert {s["stage_code"]: (s["assigned_to_me"], s["completed_at"]) for s in entry["stages"]} == {
        "FRAME": (False, None), "LEAF": (True, None), "FINISH": (False, None)}
    assert no_price_words(snapshot)
    cursor = cold.json()["next_cursor"]

    # A completes FRAME: B receives the stage change (done, not by them); the door version is unchanged.
    assert client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete", json={}).status_code == 200
    pulled = client_b.post("/api/v1/installer/sync", json={"since_cursor": cursor, "device_id": "b-phone"}).json()
    assert pulled["snapshot"] is None
    stage_changes = [c for c in pulled["changes"] if c["change_type"] == "DOOR_STAGES"]
    assert len(stage_changes) == 1
    frame = next(s for s in stage_changes[0]["payload"]["stages"] if s["stage_code"] == "FRAME")
    assert frame["completed_at"] and frame["completed_by_me"] is False and frame["assigned_to_me"] is False
    assert no_price_words(pulled["changes"])
    cursor = pulled["next_cursor"]

    # B completes LEAF offline: the door is installed; A, who never held the door, gets the installed door too.
    event = {"client_event_id": "stage-" + uuid.uuid4().hex, "type": "DOOR_STAGE_COMPLETE", "project_id": str(door.project_id),
             "happened_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
             "payload": {"door_id": str(door.id), "stage_code": "LEAF", "previous_version": 1}}
    ack = client_b.post("/api/v1/installer/sync", json={"since_cursor": cursor, "events": [event]}).json()
    assert ack["acks"][0]["ok"] and ack["acks"][0]["applied"], ack
    for client in (client_a, client_b):
        pulled = client.post("/api/v1/installer/sync", json={"since_cursor": cursor}).json()
        kinds = {(c["change_type"], c["payload"].get("status")) for c in pulled["changes"]}
        assert ("DOOR", "INSTALLED") in kinds and ("DOOR_STAGES", None) in kinds, kinds
    rows = db_session.scalars(select(SyncChangeLogORM).where(SyncChangeLogORM.entity_id == door.id)).all()
    assert all(no_price_words(row.payload) for row in rows)
    assert {row.installer_id for row in rows if row.change_type.value == "DOOR_STAGES"} == {a.id, b.id}
    client_b.close()
