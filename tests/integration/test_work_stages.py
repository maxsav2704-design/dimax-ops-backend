"""Work stages (0088): catalog, versioned plans, door plans, per-stage installers, immutable facts, completion by
stages without the legacy full-door earning, and the legacy paths refusing stage doors."""
import runpy
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import get_uow, require_admin, require_installer
from app.core.config import settings
from app.main import create_app
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.history_models import DoorStatusHistoryORM
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.doors.infrastructure.stage_models import (
    DoorStageAssignmentORM, DoorStageFactORM, DoorTypeStagePlanItemORM, DoorTypeStagePlanORM, DoorWorkPlanORM,
    WorkStageDefinitionORM,
)
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.sync.infrastructure.models import SyncEventORM
from fastapi.testclient import TestClient
from tests.conftest import TestSessionLocal, TestUnitOfWork

ADMIN = "/api/v1/admin"


@pytest.fixture(autouse=True)
def stages_enabled(monkeypatch, db_session, company_id):
    monkeypatch.setattr(settings, "WORK_STAGES_ENABLED", True)
    yield
    db_session.rollback()
    db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))
    for model in (DoorStageFactORM, DoorStageAssignmentORM, DoorWorkPlanORM, DoorTypeStagePlanItemORM,
                  DoorTypeStagePlanORM, WorkStageDefinitionORM):
        db_session.execute(delete(model).where(model.company_id == company_id))
    db_session.commit()


def installer_client(installer_user, db_session, name):
    row = InstallerORM(company_id=installer_user.company_id, full_name=name, phone=f"+1555{uuid.uuid4().hex[:8]}", email=None,
                       address=None, passport_id=None, notes=None, status="ACTIVE", is_active=True, user_id=installer_user.id)
    db_session.add(row)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_uow] = lambda: TestUnitOfWork(TestSessionLocal)
    app.dependency_overrides[require_installer] = lambda: installer_user
    app.dependency_overrides[get_current_installer_id] = lambda: row.id
    return TestClient(app), row


@pytest.fixture()
def crew(installer_user, db_session, make_installer):
    """Installer A with an API client; installer B as a plain record (office records their stage)."""
    client_a, a = installer_client(installer_user, db_session, "Stage Installer A")
    b = make_installer(full_name="Stage Installer B")
    yield client_a, a, b
    client_a.close()


@pytest.fixture()
def owner(client_admin_real_uow, admin_user):
    client_admin_real_uow.app.dependency_overrides[require_admin] = lambda: replace(admin_user, admin_scope="OWNER")
    return client_admin_real_uow


@pytest.fixture()
def catalog(owner):
    for code, name, order in (("FRAME", "Frame", 10), ("LEAF", "Leaf", 20), ("FINISH", "Finishing", 30)):
        assert owner.post(f"{ADMIN}/work-stages", json={"code": code, "name": name, "sort_order": order}).status_code == 201
    return ["FRAME", "LEAF", "FINISH"]


def make_door(db_session, company_id, door_type_id, *, installer_id=None, unit="S-1"):
    project = ProjectORM(company_id=company_id, name=f"Stages {uuid.uuid4().hex[:6]}", address="Synthetic", status="OK")
    db_session.add(project)
    db_session.flush()
    door = DoorORM(company_id=company_id, project_id=project.id, door_type_id=door_type_id, unit_label=unit, status=DoorStatus.NOT_INSTALLED,
                   version=1, our_price=Decimal("500"), is_locked=False, installer_id=installer_id)
    db_session.add(door)
    db_session.commit()
    return door


def planned_door(owner, db_session, company_id, make_door_type, catalog, *, installer_id=None):
    door_type = make_door_type(name="Staged entrance")
    plan = owner.post(f"{ADMIN}/door-types/{door_type.id}/stage-plans", json={
        "expected_latest_version": 0, "reason": "Two required stages, finishing optional",
        "items": [{"stage_code": "FRAME"}, {"stage_code": "LEAF"}, {"stage_code": "FINISH", "required": False}]})
    assert plan.status_code == 201, plan.text
    door = make_door(db_session, company_id, door_type.id, installer_id=installer_id)
    applied = owner.post(f"{ADMIN}/doors/{door.id}/work-plan", json={"plan_id": plan.json()["id"]})
    assert applied.status_code == 200, applied.text
    return door, plan.json()


# ---- catalog and plans -----------------------------------------------------------------------------------------

def test_catalog_and_versioned_plans(owner, make_door_type, db_session):
    assert owner.post(f"{ADMIN}/work-stages", json={"code": "frame", "name": "Frame"}).status_code == 201
    assert owner.post(f"{ADMIN}/work-stages", json={"code": "FRAME", "name": "Again"}).status_code == 409
    assert owner.post(f"{ADMIN}/work-stages", json={"code": "1BAD", "name": "x"}).status_code == 422
    assert owner.post(f"{ADMIN}/work-stages", json={"code": "LEAF", "name": "Leaf", "price": 1}).status_code == 422
    assert owner.post(f"{ADMIN}/work-stages", json={"code": "LEAF", "name": "Leaf"}).status_code == 201
    listed = owner.get(f"{ADMIN}/work-stages").json()
    assert [row["code"] for row in listed] == ["FRAME", "LEAF"]
    door_type = make_door_type(name="Planned type")
    url = f"{ADMIN}/door-types/{door_type.id}/stage-plans"
    assert owner.post(url, json={"expected_latest_version": 0, "reason": "r", "items": []}).status_code == 422
    assert owner.post(url, json={"expected_latest_version": 0, "reason": "r", "items": [{"stage_code": "FRAME", "required": False}]}).status_code == 422
    assert owner.post(url, json={"expected_latest_version": 0, "reason": "r", "items": [{"stage_code": "FRAME"}, {"stage_code": "FRAME"}]}).status_code == 422
    assert owner.post(url, json={"expected_latest_version": 0, "reason": "r", "items": [{"stage_code": "GHOST"}]}).status_code == 422
    first = owner.post(url, json={"expected_latest_version": 0, "reason": "Initial", "items": [{"stage_code": "FRAME"}, {"stage_code": "LEAF"}]})
    assert first.status_code == 201 and first.json()["version"] == 1 and [i["sequence"] for i in first.json()["items"]] == [1, 2]
    assert owner.post(url, json={"expected_latest_version": 0, "reason": "Stale", "items": [{"stage_code": "FRAME"}]}).status_code == 409
    assert owner.patch(f"{ADMIN}/work-stages/LEAF", json={"is_active": False}).status_code == 200
    assert owner.post(url, json={"expected_latest_version": 1, "reason": "Uses inactive", "items": [{"stage_code": "LEAF"}]}).status_code == 422
    second = owner.post(url, json={"expected_latest_version": 1, "reason": "Frame only", "items": [{"stage_code": "FRAME"}]})
    assert second.status_code == 201 and second.json()["version"] == 2
    page = owner.get(url).json()
    assert page["latest_version"] == 2 and [p["version"] for p in page["items"]] == [2, 1]


def test_planning_needs_owner_or_operations_and_the_flag(owner, admin_user, monkeypatch, make_door_type):
    owner.app.dependency_overrides[require_admin] = lambda: replace(admin_user, admin_scope="FINANCE")
    assert owner.post(f"{ADMIN}/work-stages", json={"code": "FRAME", "name": "Frame"}).status_code == 403
    assert owner.get(f"{ADMIN}/work-stages").status_code == 200
    owner.app.dependency_overrides[require_admin] = lambda: replace(admin_user, admin_scope="OPERATIONS")
    assert owner.post(f"{ADMIN}/work-stages", json={"code": "FRAME", "name": "Frame"}).status_code == 201
    monkeypatch.setattr(settings, "WORK_STAGES_ENABLED", False)
    assert owner.get(f"{ADMIN}/work-stages").status_code == 409
    assert owner.post(f"{ADMIN}/work-stages", json={"code": "LEAF", "name": "Leaf"}).status_code == 409


# ---- door plan, assignments, completion ----------------------------------------------------------------------------

def test_two_installers_complete_a_door_by_stages_without_legacy_earning(owner, crew, db_session, company_id, make_door_type, catalog):
    client_a, a, b = crew
    door, plan = planned_door(owner, db_session, company_id, make_door_type, catalog)
    stages = f"{ADMIN}/doors/{door.id}/stages"
    view = owner.get(stages).json()
    assert view["plan_version"] == 1 and view["required_total"] == 2 and view["required_done"] == 0
    assert [s["stage_code"] for s in view["stages"]] == ["FRAME", "LEAF", "FINISH"]
    # Nobody assigned yet: neither installer may complete.
    assert client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete", json={}).status_code == 403
    assert owner.post(f"{stages}/FRAME/assign", json={"installer_id": str(a.id)}).status_code == 200
    assert owner.post(f"{stages}/LEAF/assign", json={"installer_id": str(b.id)}).status_code == 200
    assert owner.post(f"{stages}/GHOST/assign", json={"installer_id": str(a.id)}).status_code == 422
    assert owner.post(f"{stages}/LEAF/assign", json={"installer_id": str(uuid.uuid4())}).status_code == 422
    # A completes FRAME (idempotent by request_id); the door stays NOT_INSTALLED with one required stage left.
    request_id = str(uuid.uuid4())
    first = client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete",
                          json={"request_id": request_id, "happened_at": "2026-10-20T08:00:00Z"})
    assert first.status_code == 200, first.text
    assert first.json()["applied"] and first.json()["required_done"] == 1 and not first.json()["door_installed"]
    again = client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete", json={"request_id": request_id})
    assert again.status_code == 200 and again.json()["applied"] is False
    assert client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete", json={}).status_code == 409
    assert client_a.post(f"/api/v1/installer/doors/{door.id}/stages/LEAF/complete", json={}).status_code == 403  # B's stage
    assert client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete", json={"price": "5"}).status_code == 422
    # The executed stage cannot be reassigned; the plan cannot change any more.
    assert owner.post(f"{stages}/FRAME/assign", json={"installer_id": str(b.id)}).status_code == 409
    other = owner.post(f"{ADMIN}/door-types/{door.door_type_id}/stage-plans", json={
        "expected_latest_version": 1, "reason": "Frame only", "items": [{"stage_code": "FRAME"}]}).json()
    assert owner.post(f"{ADMIN}/doors/{door.id}/work-plan", json={"plan_id": other["id"]}).status_code == 409
    db_session.expire_all()
    assert db_session.get(DoorORM, door.id).status == DoorStatus.NOT_INSTALLED
    # The office records B's LEAF (reported by phone): every required stage is done, the door is installed.
    done = owner.post(f"{stages}/LEAF/complete", json={"installer_id": str(b.id), "happened_at": "2026-10-21T09:30:00Z"})
    assert done.status_code == 200, done.text
    assert done.json()["door_installed"] and done.json()["status"] == "INSTALLED" and done.json()["version"] == 2
    db_session.expire_all()
    fresh = db_session.get(DoorORM, door.id)
    assert fresh.status == DoorStatus.INSTALLED and fresh.is_locked and fresh.installed_at == datetime(2026, 10, 21, 9, 30, tzinfo=timezone.utc)
    assert db_session.scalar(select(func.count()).select_from(CompletedWorkORM).where(CompletedWorkORM.door_id == door.id)) == 0
    assert db_session.scalar(select(func.count()).select_from(DoorStatusHistoryORM).where(DoorStatusHistoryORM.door_id == door.id)) == 1
    facts = db_session.scalars(select(DoorStageFactORM).where(DoorStageFactORM.door_id == door.id).order_by(DoorStageFactORM.happened_at)).all()
    assert [(f.stage_code, f.installer_id, f.source) for f in facts] == [("FRAME", a.id, "API"), ("LEAF", b.id, "ADMIN")]
    actions = db_session.scalars(select(AuditLogORM.action).where(AuditLogORM.company_id == company_id, AuditLogORM.entity_id == door.id)).all()
    assert actions.count("DOOR_STAGE_COMPLETE") == 2 and "DOOR_WORK_PLAN" in actions and actions.count("DOOR_STAGE_ASSIGN") == 2
    view = owner.get(stages).json()
    assert view["installed_by_stages"] and view["required_done"] == 2 and view["door_status"] == "INSTALLED"
    # The optional stage after installation is refused: the door is locked.
    assert owner.post(f"{stages}/FINISH/assign", json={"installer_id": str(a.id)}).status_code == 200
    assert client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FINISH/complete", json={}).status_code == 409
    # Facts are immutable.
    fact = facts[0]
    fact.installer_id = b.id
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    db_session.delete(db_session.get(DoorStageFactORM, fact.id))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_assignment_history_and_installer_view(owner, crew, db_session, company_id, make_door_type, catalog):
    client_a, a, b = crew
    door, _ = planned_door(owner, db_session, company_id, make_door_type, catalog)
    stages = f"{ADMIN}/doors/{door.id}/stages"
    assert client_a.get(f"/api/v1/installer/doors/{door.id}/stages").status_code == 404  # no assignment yet
    assert owner.post(f"{stages}/FRAME/assign", json={"installer_id": str(b.id)}).status_code == 200
    assert owner.post(f"{stages}/FRAME/assign", json={"installer_id": str(a.id)}).status_code == 200
    rows = db_session.scalars(select(DoorStageAssignmentORM).where(DoorStageAssignmentORM.door_id == door.id)
                              .order_by(DoorStageAssignmentORM.assigned_at)).all()
    assert [(r.installer_id, r.replaced_at is not None) for r in rows] == [(b.id, True), (a.id, False)]
    mine = client_a.get(f"/api/v1/installer/doors/{door.id}/stages").json()
    assert mine["stages"][0]["installer_id"] == str(a.id) and mine["stages"][1]["installer_id"] is None
    assert owner.get(f"{ADMIN}/doors/{uuid.uuid4()}/stages").status_code == 404


def test_legacy_installation_refuses_stage_doors_and_plain_doors_keep_working(owner, crew, db_session, company_id, make_door_type, catalog):
    client_a, a, _ = crew
    door, _ = planned_door(owner, db_session, company_id, make_door_type, catalog, installer_id=a.id)
    door.installer_rate_snapshot = Decimal("75.00")
    db_session.commit()
    assert client_a.post(f"/api/v1/installer/doors/{door.id}/install", json={}).status_code == 409
    assert client_a.patch(f"/api/v1/installer/doors/{door.id}/status", json={"status": "IN_PROGRESS"}).status_code == 200
    assert client_a.patch(f"/api/v1/installer/doors/{door.id}/status", json={"status": "INSTALLED"}).status_code == 409
    assert owner.post(f"{ADMIN}/doors/{door.id}/install").status_code == 409
    assert owner.post(f"{ADMIN}/doors/{door.id}/override", json={"new_status": "INSTALLED", "override_reason": "test"}).status_code == 409
    db_session.expire_all()
    assert db_session.get(DoorORM, door.id).status == DoorStatus.IN_PROGRESS
    assert db_session.scalar(select(func.count()).select_from(CompletedWorkORM).where(CompletedWorkORM.door_id == door.id)) == 0
    # A door without a plan installs exactly as before and earns the full installation.
    plain = make_door(db_session, company_id, door.door_type_id, installer_id=a.id, unit="S-2")
    plain.installer_rate_snapshot = Decimal("75.00")
    db_session.commit()
    assert owner.get(f"{ADMIN}/doors/{plain.id}/stages").json() is None
    installed = client_a.post(f"/api/v1/installer/doors/{plain.id}/install", json={})
    assert installed.status_code == 200, installed.text
    assert db_session.scalar(select(func.count()).select_from(CompletedWorkORM).where(CompletedWorkORM.door_id == plain.id)) == 1


def test_offline_stage_event_is_applied_once_and_checks_the_assignment(owner, crew, db_session, company_id, make_door_type, catalog):
    client_a, a, b = crew
    door, _ = planned_door(owner, db_session, company_id, make_door_type, catalog)
    stages = f"{ADMIN}/doors/{door.id}/stages"
    assert owner.post(f"{stages}/FRAME/assign", json={"installer_id": str(a.id)}).status_code == 200
    assert owner.post(f"{stages}/LEAF/assign", json={"installer_id": str(b.id)}).status_code == 200
    event = {"client_event_id": "stage-" + uuid.uuid4().hex, "type": "DOOR_STAGE_COMPLETE", "project_id": str(door.project_id),
             "happened_at": "2026-10-20T10:00:00+02:00", "payload": {"door_id": str(door.id), "stage_code": "FRAME", "previous_version": 1}}
    first = client_a.post("/api/v1/installer/sync", json={"events": [event]})
    assert first.status_code == 200, first.text
    ack = first.json()["acks"][0]
    assert ack["ok"] and ack["applied"], ack
    replay = client_a.post("/api/v1/installer/sync", json={"events": [event]}).json()["acks"][0]
    assert replay["ok"] and replay["applied"] is False
    assert db_session.scalar(select(func.count()).select_from(DoorStageFactORM).where(DoorStageFactORM.door_id == door.id)) == 1
    assert db_session.scalar(select(SyncEventORM.client_event_id).where(SyncEventORM.client_event_id == event["client_event_id"])) is not None
    # A's device cannot complete B's stage; a priced payload is refused; an unknown stage is a conflict.
    other = {**event, "client_event_id": "stage-" + uuid.uuid4().hex, "payload": {"door_id": str(door.id), "stage_code": "LEAF"}}
    ack = client_a.post("/api/v1/installer/sync", json={"events": [other]}).json()["acks"][0]
    assert not ack["ok"] and ack["error"] == "CONFLICT_ASSIGNMENT_CHANGED", ack
    priced = {**event, "client_event_id": "stage-" + uuid.uuid4().hex, "payload": {"door_id": str(door.id), "stage_code": "FINISH", "price_list_id": str(uuid.uuid4())}}
    ack = client_a.post("/api/v1/installer/sync", json={"events": [priced]}).json()["acks"][0]
    assert not ack["ok"], ack
    db_session.expire_all()
    assert db_session.get(DoorORM, door.id).status == DoorStatus.NOT_INSTALLED
    assert db_session.scalar(select(func.count()).select_from(CompletedWorkORM).where(CompletedWorkORM.door_id == door.id)) == 0


def test_downgrade_refuses_to_discard_stage_facts(owner, crew, db_session, company_id, make_door_type, catalog, monkeypatch):
    client_a, a, _ = crew
    door, _ = planned_door(owner, db_session, company_id, make_door_type, catalog)
    assert owner.post(f"{ADMIN}/doors/{door.id}/stages/FRAME/assign", json={"installer_id": str(a.id)}).status_code == 200
    assert client_a.post(f"/api/v1/installer/doors/{door.id}/stages/FRAME/complete", json={}).status_code == 200
    downgrade = runpy.run_path("alembic/versions/0088_work_stages.py")["downgrade"]
    monkeypatch.setitem(downgrade.__globals__, "op", Operations(MigrationContext.configure(db_session.connection())))
    with pytest.raises(RuntimeError, match="stage execution facts"):
        downgrade()
    db_session.rollback()
