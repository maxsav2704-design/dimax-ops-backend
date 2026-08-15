from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.modules.addons.domain.enums import AddonFactSource
from app.modules.addons.infrastructure.models import (
    AddonTypeORM,
    ProjectAddonFactORM,
    ProjectAddonPlanORM,
)
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.sync.application.service import InstallerSyncService
from app.modules.sync.domain.enums import SyncChangeType, SyncEventType
from app.modules.sync.infrastructure.models import SyncChangeLogORM, SyncEventORM
from app.modules.sync.infrastructure.repositories import SyncEventRepository
from app.shared.domain.errors import ValidationError


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_installer_sync_rejects_ack_cursor_ahead_of_server(
    client_installer,
    db_session,
    company_id,
    installer_user,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Cursor Bounds Installer",
        phone="+10000000900",
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

    response = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 1,
            "events": [],
            "device_id": "cursor-bounds-device",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["field"] == "ack_cursor"

def test_installer_sync_issue_create_is_idempotent_and_updates_assigned_door(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Issue Sync Installer",
        phone="+10000000901",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    project = ProjectORM(
        company_id=company_id,
        name="Issue Sync Project",
        address="1 Issue Street",
        status=ProjectStatus.OK,
    )
    db_session.add_all([installer, project])
    db_session.flush()
    door_type = make_door_type(name="Issue Sync Door")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="ISSUE-SYNC-1",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        installed_at=None,
        is_locked=False,
        version=0,
    )
    db_session.add(door)
    db_session.commit()

    payload = {
        "since_cursor": 0,
        "ack_cursor": 0,
        "events": [
            {
                "client_event_id": "issue-create-event-1",
                "type": "ISSUE_CREATE",
                "project_id": str(project.id),
                "payload": {
                    "door_id": str(door.id),
                    "title": "Opening is blocked",
                    "details": "Concrete work is not complete",
                },
            }
        ],
        "app_version": "mobile-test",
        "device_id": "device-issue-create",
    }

    first_response = client_installer.post("/api/v1/installer/sync", json=payload)
    assert first_response.status_code == 200, first_response.text
    assert first_response.json()["acks"][0] == {
        "client_event_id": "issue-create-event-1",
        "ok": True,
        "applied": True,
        "error": None,
    }

    second_response = client_installer.post("/api/v1/installer/sync", json=payload)
    assert second_response.status_code == 200, second_response.text
    assert second_response.json()["acks"][0]["ok"] is True
    assert second_response.json()["acks"][0]["applied"] is False

    issue = (
        db_session.query(IssueORM)
        .filter(
            IssueORM.company_id == company_id,
            IssueORM.door_id == door.id,
        )
        .one()
    )
    assert issue.title == "Opening is blocked"
    assert issue.details == "Concrete work is not complete"
    assert issue.created_by_user_id == installer_user.id

    db_session.refresh(door)
    assert door.status == DoorStatus.ISSUE_OPEN
    assert door.version == 1
    assert (
        db_session.query(SyncEventORM)
        .filter(SyncEventORM.client_event_id == "issue-create-event-1")
        .count()
        == 1
    )


def test_installer_sync_concurrent_duplicate_returns_idempotent_ack(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
    monkeypatch,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Concurrent Sync Installer",
        phone="+10000000908",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    project = ProjectORM(
        company_id=company_id,
        name="Concurrent Sync Project",
        address="8 Race Street",
        status=ProjectStatus.OK,
    )
    db_session.add_all([installer, project])
    db_session.flush()
    door_type = make_door_type(name="Concurrent Sync Door")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="SYNC-RACE-1",
        our_price="100.00",
        status=DoorStatus.IN_PROGRESS,
        installer_id=installer.id,
        installed_at=None,
        is_locked=False,
        version=1,
    )
    db_session.add(door)
    db_session.flush()
    competing_event = SyncEventORM(
        company_id=company_id,
        installer_id=installer.id,
        project_id=project.id,
        event_type=SyncEventType.DOOR_SET_STATUS,
        client_event_id="concurrent-event-1",
        client_happened_at=datetime.now(timezone.utc),
        payload={
            "door_id": str(door.id),
            "status": "IN_PROGRESS",
            "expected_version": 0,
        },
        applied_at=datetime.now(timezone.utc),
        apply_error=None,
    )
    db_session.add(competing_event)
    db_session.commit()

    original_get = SyncEventRepository.get_by_client_event
    lookup_count = 0

    def miss_first_lookup(self, *, company_id, client_event_id):
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 1 and client_event_id == "concurrent-event-1":
            return None
        return original_get(
            self,
            company_id=company_id,
            client_event_id=client_event_id,
        )

    monkeypatch.setattr(
        SyncEventRepository,
        "get_by_client_event",
        miss_first_lookup,
    )

    response = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [
                {
                    "client_event_id": "concurrent-event-1",
                    "type": "DOOR_SET_STATUS",
                    "project_id": str(project.id),
                    "payload": {
                        "door_id": str(door.id),
                        "status": "IN_PROGRESS",
                        "expected_version": 0,
                    },
                }
            ],
            "device_id": "concurrent-sync-device",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["acks"] == [
        {
            "client_event_id": "concurrent-event-1",
            "ok": True,
            "applied": False,
            "error": None,
        }
    ]
    assert lookup_count >= 2

    db_session.expire_all()
    persisted_door = db_session.query(DoorORM).filter(DoorORM.id == door.id).one()
    assert persisted_door.status == DoorStatus.IN_PROGRESS
    assert persisted_door.version == 1
    assert (
        db_session.query(SyncEventORM)
        .filter(
            SyncEventORM.company_id == company_id,
            SyncEventORM.client_event_id == "concurrent-event-1",
        )
        .count()
        == 1
    )


def test_installer_sync_event_rolls_back_partial_changes_and_records_failure(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
    monkeypatch,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Event Savepoint Installer",
        phone="+10000000904",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    project = ProjectORM(
        company_id=company_id,
        name="Event Savepoint Project",
        address="3 Issue Street",
        status=ProjectStatus.OK,
    )
    db_session.add_all([installer, project])
    db_session.flush()
    door_type = make_door_type(name="Event Savepoint Door")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="ISSUE-SYNC-SAVEPOINT",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        installed_at=None,
        is_locked=False,
        version=0,
    )
    db_session.add(door)
    db_session.commit()

    def _mutate_then_fail(uow, **kwargs):
        target = uow.doors.get(company_id=company_id, door_id=door.id)
        target.comment = "must be rolled back"
        uow.session.flush()
        raise ValidationError("forced event conflict")

    monkeypatch.setattr(
        InstallerSyncService,
        "_apply_issue_create",
        staticmethod(_mutate_then_fail),
    )

    response = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [
                {
                    "client_event_id": "issue-savepoint-event-1",
                    "type": "ISSUE_CREATE",
                    "project_id": str(project.id),
                    "payload": {
                        "door_id": str(door.id),
                        "title": "Savepoint check",
                    },
                }
            ],
            "device_id": "event-savepoint-device",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["acks"] == [
        {
            "client_event_id": "issue-savepoint-event-1",
            "ok": False,
            "applied": False,
            "error": "CONFLICT_INVALID_TRANSITION",
        }
    ]

    db_session.expire_all()
    persisted_door = db_session.query(DoorORM).filter(DoorORM.id == door.id).one()
    assert persisted_door.comment is None
    failed_event = (
        db_session.query(SyncEventORM)
        .filter(
            SyncEventORM.company_id == company_id,
            SyncEventORM.client_event_id == "issue-savepoint-event-1",
        )
        .one()
    )
    assert failed_event.apply_error == "CONFLICT_INVALID_TRANSITION"


def test_installer_sync_issue_create_rejects_unassigned_door(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Issue Sync Current Installer",
        phone="+10000000902",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    other_installer = InstallerORM(
        company_id=company_id,
        full_name="Issue Sync Other Installer",
        phone="+10000000903",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=None,
    )
    project = ProjectORM(
        company_id=company_id,
        name="Unassigned Issue Sync Project",
        address="2 Issue Street",
        status=ProjectStatus.OK,
    )
    db_session.add_all([installer, other_installer, project])
    db_session.flush()
    door_type = make_door_type(name="Unassigned Issue Sync Door")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="ISSUE-SYNC-OTHER",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=other_installer.id,
        installed_at=None,
        is_locked=False,
        version=0,
    )
    db_session.add(door)
    db_session.commit()

    response = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [
                {
                    "client_event_id": "issue-create-event-unassigned",
                    "type": "ISSUE_CREATE",
                    "project_id": str(project.id),
                    "payload": {
                        "door_id": str(door.id),
                        "title": "Must not be created",
                    },
                }
            ],
            "app_version": "mobile-test",
            "device_id": "device-issue-unassigned",
        },
    )
    assert response.status_code == 200, response.text
    ack = response.json()["acks"][0]
    assert ack["ok"] is False
    assert ack["applied"] is False
    assert ack["error"] == "CONFLICT_ASSIGNMENT_CHANGED"
    assert (
        db_session.query(IssueORM)
        .filter(
            IssueORM.company_id == company_id,
            IssueORM.door_id == door.id,
        )
        .count()
        == 0
    )


def test_installer_sync_reset_snapshot_includes_projects(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
    make_reason,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Snapshot Installer",
        phone="+10000000041",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="Snapshot Project",
        address="1 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Snapshot Door")
    reason = make_reason(code="MISSING_FRAME", name="Missing frame")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="SNAP-100",
        order_number="AZ-100",
        house_number="1",
        floor_label="2",
        apartment_number="21",
        location_code="DIRA",
        door_marking="A",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        reason_id=reason.id,
        comment="Frame is missing",
        installed_at=None,
        is_locked=False,
        version=7,
    )
    db_session.add(door)
    db_session.flush()
    issue = IssueORM(
        company_id=company_id,
        door_id=door.id,
        title="Snapshot issue",
        details="Opening is blocked",
        created_by_user_id=installer_user.id,
    )
    db_session.add(issue)
    locked_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="SNAP-101",
        order_number="AZ-101",
        house_number="1",
        floor_label="2",
        apartment_number="22",
        location_code="DIRA",
        door_marking="B",
        our_price="100.00",
        status=DoorStatus.INSTALLED,
        installer_id=installer.id,
        reason_id=None,
        comment=None,
        installed_at=datetime.now(timezone.utc),
        is_locked=True,
        version=3,
    )
    db_session.add(locked_door)
    unassigned_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="SNAP-OTHER",
        order_number="AZ-OTHER",
        house_number="1",
        floor_label="2",
        apartment_number="23",
        location_code="DIRA",
        door_marking="C",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(unassigned_door)
    db_session.flush()
    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Snapshot Addon",
        unit="pcs",
        default_client_price=Decimal("30.00"),
        default_installer_price=Decimal("12.00"),
        is_active=True,
        deleted_at=None,
    )
    db_session.add(addon_type)
    db_session.flush()
    addon_plan = ProjectAddonPlanORM(
        company_id=company_id,
        project_id=project.id,
        addon_type_id=addon_type.id,
        qty_planned=Decimal("2.00"),
        client_price=Decimal("30.00"),
        installer_price=Decimal("12.00"),
    )
    db_session.add(addon_plan)
    db_session.flush()
    addon_fact = ProjectAddonFactORM(
        company_id=company_id,
        project_id=project.id,
        addon_type_id=addon_type.id,
        installer_id=installer.id,
        qty_done=Decimal("1.00"),
        done_at=datetime.now(timezone.utc),
        comment="snapshot done",
        source=AddonFactSource.ONLINE,
        client_event_id="snapshot-addon-fact",
    )
    db_session.add(addon_fact)
    db_session.flush()
    stale_project = ProjectORM(
        company_id=company_id,
        name="Stale Snapshot Project",
        address="99 Old Street",
        status=ProjectStatus.OK,
    )
    db_session.add(stale_project)
    db_session.flush()
    db_session.add(
        ProjectAddonPlanORM(
            company_id=company_id,
            project_id=stale_project.id,
            addon_type_id=addon_type.id,
            qty_planned=Decimal("9.00"),
            client_price=Decimal("90.00"),
            installer_price=Decimal("45.00"),
        )
    )
    stale_addon_fact = ProjectAddonFactORM(
        company_id=company_id,
        project_id=stale_project.id,
        addon_type_id=addon_type.id,
        installer_id=installer.id,
        qty_done=Decimal("4.00"),
        done_at=datetime.now(timezone.utc),
        comment="stale project fact",
        source=AddonFactSource.OFFLINE,
        client_event_id="snapshot-stale-addon-fact",
    )
    db_session.add(stale_addon_fact)
    db_session.flush()
    db_session.add(
        CompletedWorkORM(
            company_id=company_id,
            project_id=project.id,
            door_id=None,
            addon_fact_id=addon_fact.id,
            installer_id=installer.id,
            completed_at=addon_fact.done_at,
            quantity=Decimal("1.00"),
            rate_snapshot=Decimal("12.00"),
            amount_snapshot=Decimal("12.00"),
            work_kind="ADDON",
            entry_type="ORIGINAL",
        )
    )
    db_session.add(
        SyncChangeLogORM(
            created_at=datetime.now(timezone.utc),
            company_id=company_id,
            change_type=SyncChangeType.DOOR,
            entity_id=door.id,
            project_id=project.id,
            installer_id=installer.id,
            payload={
                "id": str(door.id),
                "project_id": str(project.id),
                "door_type_id": str(door_type.id),
                "unit_label": door.unit_label,
                "status": "NOT_INSTALLED",
            },
        )
    )
    db_session.commit()

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [],
            "app_version": "mobile-test",
            "device_id": "device-test",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["reset_required"] is True
    assert body["snapshot"] is not None
    assert len(body["snapshot"]["projects"]) == 1
    assert body["snapshot"]["projects"][0]["id"] == str(project.id)
    assert str(stale_project.id) not in {
        item["id"] for item in body["snapshot"]["projects"]
    }
    assert body["snapshot"]["projects"][0]["name"] == "Snapshot Project"
    assert body["snapshot"]["projects"][0]["address"] == "1 Snapshot Street"
    assert body["snapshot"]["projects"][0]["status"] == "OK"
    assert body["snapshot"]["projects"][0]["waze_url"] is not None
    assert len(body["snapshot"]["doors"]) == 2
    doors_by_unit = {item["unit_label"]: item for item in body["snapshot"]["doors"]}
    assert "SNAP-OTHER" not in doors_by_unit
    assert doors_by_unit["SNAP-100"]["project_id"] == str(project.id)
    assert doors_by_unit["SNAP-100"]["status"] == "NOT_INSTALLED"
    assert doors_by_unit["SNAP-100"]["reason_id"] == str(reason.id)
    assert doors_by_unit["SNAP-100"]["comment"] == "Frame is missing"
    assert doors_by_unit["SNAP-100"]["is_locked"] is False
    assert doors_by_unit["SNAP-100"]["version"] == 7
    assert doors_by_unit["SNAP-101"]["status"] == "INSTALLED"
    assert doors_by_unit["SNAP-101"]["is_locked"] is True
    assert doors_by_unit["SNAP-101"]["version"] == 3
    assert len(body["snapshot"]["addon_plans"]) == 1
    assert body["snapshot"]["issues"] == [
        {
            "id": str(issue.id),
            "door_id": str(door.id),
            "project_id": str(project.id),
            "status": "OPEN",
            "title": "Snapshot issue",
            "details": "Opening is blocked",
        }
    ]
    assert body["snapshot"]["addon_plans"][0]["project_id"] == str(project.id)
    assert str(stale_project.id) not in {
        item["project_id"] for item in body["snapshot"]["addon_plans"]
    }
    assert body["snapshot"]["addon_plans"][0]["qty_planned"] == "2.00"
    assert "client_price" not in body["snapshot"]["addon_plans"][0]
    assert "installer_price" not in body["snapshot"]["addon_plans"][0]
    assert len(body["snapshot"]["addon_facts"]) == 1
    addon_fact_payload = body["snapshot"]["addon_facts"][0]
    assert addon_fact_payload["id"] == str(addon_fact.id)
    assert addon_fact_payload["source"] == AddonFactSource.ONLINE.value
    assert addon_fact_payload["qty_done"] == "1.00"
    assert str(stale_addon_fact.id) not in {
        item["id"] for item in body["snapshot"]["addon_facts"]
    }
    assert "client_price" not in addon_fact_payload
    assert "installer_price" not in addon_fact_payload
    assert "rate_snapshot" not in addon_fact_payload
    assert "amount_snapshot" not in addon_fact_payload
    assert "work_kind" not in addon_fact_payload
    assert "completed_work_id" not in addon_fact_payload


def test_installer_sync_door_event_records_reason_and_lock_metadata(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
    make_reason,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Reason Sync Installer",
        phone="+10000000042",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="Reason Sync Project",
        address="2 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Reason Sync Door")
    reason = make_reason(code="NO_OPENING", name="No opening")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="SYNC-100",
        order_number="RS-100",
        house_number="1",
        floor_label="3",
        apartment_number="31",
        location_code="DIRA",
        door_marking="A",
        our_price="100.00",
        status=DoorStatus.IN_PROGRESS,
        installer_id=installer.id,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(door)
    db_session.commit()

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [
                {
                    "client_event_id": "reason-event-1",
                    "type": "DOOR_SET_STATUS",
                    "project_id": str(project.id),
                    "payload": {
                        "door_id": str(door.id),
                        "status": "NOT_INSTALLED",
                        "reason_id": str(reason.id),
                        "comment": "Opening is not ready",
                    },
                }
            ],
            "app_version": "mobile-test",
            "device_id": "device-test",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["acks"][0]["ok"] is True

    change = (
        db_session.query(SyncChangeLogORM)
        .filter(SyncChangeLogORM.entity_id == door.id)
        .order_by(SyncChangeLogORM.cursor_id.desc())
        .first()
    )
    assert change is not None
    assert change.payload["status"] == "NOT_INSTALLED"
    assert change.payload["reason_id"] == str(reason.id)
    assert change.payload["comment"] == "Opening is not ready"
    assert change.payload["is_locked"] is False
    assert change.payload["version"] == 1


def test_installer_incremental_sync_sanitizes_financial_payload_fields(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Sanitized Payload Installer",
        phone="+10000000043",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="Sanitized Payload Project",
        address="3 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Sanitized Payload Door")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="SAN-100",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        installed_at=None,
        is_locked=False,
    )
    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Sanitized Addon",
        unit="pcs",
        default_client_price=Decimal("30.00"),
        default_installer_price=Decimal("12.00"),
        is_active=True,
        deleted_at=None,
    )
    db_session.add_all([door, addon_type])
    db_session.flush()

    baseline = SyncChangeLogORM(
        created_at=datetime.now(timezone.utc),
        company_id=company_id,
        change_type=SyncChangeType.PROJECT_BASE,
        entity_id=project.id,
        project_id=project.id,
        installer_id=installer.id,
        payload={"id": str(project.id), "name": project.name},
    )
    db_session.add(baseline)
    db_session.flush()
    baseline_cursor = baseline.cursor_id

    db_session.add_all(
        [
            SyncChangeLogORM(
                created_at=datetime.now(timezone.utc),
                company_id=company_id,
                change_type=SyncChangeType.PROJECT_ADDON_PLAN,
                entity_id=project.id,
                project_id=project.id,
                installer_id=None,
                payload={
                    "kind": "addon_plan_upsert",
                    "project_id": str(project.id),
                    "client_price": "90.00",
                    "installer_price": "45.00",
                    "plan_items": [
                        {
                            "addon_type_id": str(addon_type.id),
                            "qty_planned": "2.00",
                            "client_price": "90.00",
                            "installer_price": "45.00",
                        }
                    ],
                },
            ),
            SyncChangeLogORM(
                created_at=datetime.now(timezone.utc),
                company_id=company_id,
                change_type=SyncChangeType.ADDON_FACT,
                entity_id=uuid.uuid4(),
                project_id=project.id,
                installer_id=installer.id,
                payload={
                    "id": str(uuid.uuid4()),
                    "project_id": str(project.id),
                    "addon_type_id": str(addon_type.id),
                    "installer_id": str(installer.id),
                    "qty_done": "1.00",
                    "done_at": datetime.now(timezone.utc).isoformat(),
                    "comment": "sanitized",
                    "source": AddonFactSource.OFFLINE.value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "client_price": "90.00",
                    "installer_price": "45.00",
                    "rate_snapshot": "45.00",
                    "amount_snapshot": "45.00",
                },
            ),
        ]
    )
    db_session.commit()

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": baseline_cursor,
            "ack_cursor": baseline_cursor,
            "events": [],
            "app_version": "mobile-test",
            "device_id": "device-sanitized-payload",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reset_required"] is False

    changes = body["changes"]
    plan_payload = next(
        row["payload"]
        for row in changes
        if row["change_type"] == SyncChangeType.PROJECT_ADDON_PLAN.value
    )
    assert set(plan_payload) == {"kind", "project_id", "plan_items"}
    assert set(plan_payload["plan_items"][0]) == {"addon_type_id", "qty_planned"}

    fact_payload = next(
        row["payload"]
        for row in changes
        if row["change_type"] == SyncChangeType.ADDON_FACT.value
    )
    assert set(fact_payload) == {
        "id",
        "project_id",
        "addon_type_id",
        "installer_id",
        "qty_done",
        "done_at",
        "comment",
        "source",
        "updated_at",
    }


def test_installer_sync_door_event_rejects_unassigned_door_in_assigned_project(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
    make_reason,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Strict Door Sync Installer",
        phone="+10000000045",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="Strict Door Sync Project",
        address="5 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Strict Sync Door")
    reason = make_reason(code="STRICT_REASON", name="Strict reason")
    assigned_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="STRICT-MINE",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        installed_at=None,
        is_locked=False,
        version=0,
    )
    unassigned_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="STRICT-UNASSIGNED",
        our_price="100.00",
        status=DoorStatus.IN_PROGRESS,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
        version=0,
    )
    db_session.add_all([assigned_door, unassigned_door])
    db_session.commit()

    sync_body = {
        "since_cursor": 0,
        "ack_cursor": 0,
        "events": [
            {
                "client_event_id": "strict-door-event-1",
                "type": "DOOR_SET_STATUS",
                "project_id": str(project.id),
                "payload": {
                    "door_id": str(unassigned_door.id),
                    "status": "NOT_INSTALLED",
                    "reason_id": str(reason.id),
                    "comment": "Should not apply",
                },
            }
        ],
        "app_version": "mobile-test",
        "device_id": "device-strict-door",
    }

    resp = client_installer.post("/api/v1/installer/sync", json=sync_body)
    assert resp.status_code == 200, resp.text
    ack = resp.json()["acks"][0]
    assert ack["ok"] is False
    assert ack["error"] == "CONFLICT_ASSIGNMENT_CHANGED"

    db_session.refresh(unassigned_door)
    assert unassigned_door.status == DoorStatus.IN_PROGRESS
    assert unassigned_door.reason_id is None
    assert unassigned_door.comment is None
    assert unassigned_door.version == 0

    failed_event = (
        db_session.query(SyncEventORM)
        .filter(SyncEventORM.client_event_id == "strict-door-event-1")
        .one()
    )
    assert failed_event.apply_error is not None
    assert failed_event.apply_error == "CONFLICT_ASSIGNMENT_CHANGED"

    retry_resp = client_installer.post("/api/v1/installer/sync", json=sync_body)
    assert retry_resp.status_code == 200, retry_resp.text
    retry_ack = retry_resp.json()["acks"][0]
    assert retry_ack["ok"] is False
    assert retry_ack["applied"] is False
    assert retry_ack["error"] == "CONFLICT_ASSIGNMENT_CHANGED"


def test_installer_sync_addon_fact_event_rejects_unassigned_project(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
    make_installer,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Strict Addon Sync Installer",
        phone="+10000000049",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    other_installer = make_installer(
        full_name="Strict Addon Other Installer",
        phone="+972500004949",
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="Strict Addon Sync Project",
        address="9 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Strict Addon Sync Door")
    db_session.add(
        DoorORM(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            unit_label="STRICT-ADDON-OTHER",
            our_price="100.00",
            status=DoorStatus.NOT_INSTALLED,
            installer_id=other_installer.id,
            installed_at=None,
            is_locked=False,
            version=0,
        )
    )
    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Strict addon",
        unit="pcs",
        default_client_price=Decimal("30.00"),
        default_installer_price=Decimal("12.00"),
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
            client_price=Decimal("30.00"),
            installer_price=Decimal("12.00"),
        )
    )
    db_session.commit()

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [
                {
                    "client_event_id": "strict-addon-event-1",
                    "type": "ADDON_FACT_CREATE",
                    "project_id": str(project.id),
                    "payload": {
                        "addon_type_id": str(addon_type.id),
                        "qty_done": "1.00",
                        "comment": "Should not apply",
                    },
                }
            ],
            "app_version": "mobile-test",
            "device_id": "device-strict-addon",
        },
    )
    assert resp.status_code == 200, resp.text
    ack = resp.json()["acks"][0]
    assert ack["ok"] is False
    assert ack["applied"] is False
    assert ack["error"] == "CONFLICT_ASSIGNMENT_CHANGED"

    assert (
        db_session.query(ProjectAddonFactORM)
        .filter(
            ProjectAddonFactORM.company_id == company_id,
            ProjectAddonFactORM.client_event_id == "strict-addon-event-1",
        )
        .count()
        == 0
    )
    assert (
        db_session.query(CompletedWorkORM)
        .filter(CompletedWorkORM.company_id == company_id)
        .filter(CompletedWorkORM.project_id == project.id)
        .count()
        == 0
    )

    failed_event = (
        db_session.query(SyncEventORM)
        .filter(SyncEventORM.client_event_id == "strict-addon-event-1")
        .one()
    )
    assert failed_event.apply_error == "CONFLICT_ASSIGNMENT_CHANGED"


def test_installer_sync_rejects_duplicate_client_event_owned_by_another_installer(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
    make_installer,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Duplicate Event Current Installer",
        phone="+10000000047",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    other_installer = make_installer(
        full_name="Duplicate Event Other Installer",
        phone="+972500004747",
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="Duplicate Event Project",
        address="7 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Duplicate Event Door")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="DUP-100",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        installed_at=None,
        is_locked=False,
        version=0,
    )
    db_session.add(door)
    db_session.add(
        SyncEventORM(
            company_id=company_id,
            installer_id=other_installer.id,
            project_id=project.id,
            event_type=SyncEventType.DOOR_SET_STATUS,
            client_event_id="duplicate-event-1",
            client_happened_at=datetime.now(timezone.utc),
            payload={"door_id": str(door.id), "status": "INSTALLED"},
            applied_at=datetime.now(timezone.utc),
            apply_error=None,
        )
    )
    db_session.commit()

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [
                {
                    "client_event_id": "duplicate-event-1",
                    "type": "DOOR_SET_STATUS",
                    "project_id": str(project.id),
                    "payload": {
                        "door_id": str(door.id),
                        "status": "INSTALLED",
                    },
                }
            ],
            "app_version": "mobile-test",
            "device_id": "device-duplicate-event",
        },
    )
    assert resp.status_code == 200, resp.text
    ack = resp.json()["acks"][0]
    assert ack == {
        "client_event_id": "duplicate-event-1",
        "ok": False,
        "applied": False,
        "error": "CONFLICT_ASSIGNMENT_CHANGED",
    }

    db_session.refresh(door)
    assert door.status == DoorStatus.NOT_INSTALLED
    assert door.version == 0
    assert (
        db_session.query(SyncEventORM)
        .filter(SyncEventORM.client_event_id == "duplicate-event-1")
        .count()
        == 1
    )


def test_installer_sync_installed_event_increments_version_and_payload(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Version Sync Installer",
        phone="+10000000046",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="Version Sync Project",
        address="6 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Version Sync Door")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="VERSION-100",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        installed_at=None,
        is_locked=False,
        version=0,
        installer_rate_snapshot=Decimal("70.00"),
    )
    db_session.add(door)
    db_session.commit()

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [
                {
                    "client_event_id": "version-door-event-1",
                    "type": "DOOR_SET_STATUS",
                    "project_id": str(project.id),
                    "payload": {
                        "door_id": str(door.id),
                        "status": "INSTALLED",
                    },
                }
            ],
            "app_version": "mobile-test",
            "device_id": "device-version-door",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["acks"][0]["ok"] is True

    db_session.refresh(door)
    assert door.status == DoorStatus.INSTALLED
    assert door.is_locked is True
    assert door.version == 1

    change = (
        db_session.query(SyncChangeLogORM)
        .filter(SyncChangeLogORM.entity_id == door.id)
        .order_by(SyncChangeLogORM.cursor_id.desc())
        .first()
    )
    assert change is not None
    assert change.payload["status"] == "INSTALLED"
    assert change.payload["version"] == 1


def test_installer_sync_door_event_rejects_stale_previous_version(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Stale Version Sync Installer",
        phone="+10000000048",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="Stale Version Sync Project",
        address="8 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Stale Version Sync Door")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="STALE-100",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        installed_at=None,
        is_locked=False,
        version=2,
    )
    db_session.add(door)
    db_session.commit()

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [
                {
                    "client_event_id": "stale-version-event-1",
                    "type": "DOOR_SET_STATUS",
                    "project_id": str(project.id),
                    "payload": {
                        "door_id": str(door.id),
                        "status": "INSTALLED",
                        "previous_version": 1,
                    },
                }
            ],
            "app_version": "mobile-test",
            "device_id": "device-stale-version",
        },
    )
    assert resp.status_code == 200, resp.text
    ack = resp.json()["acks"][0]
    assert ack["ok"] is False
    assert ack["applied"] is False
    assert ack["error"] == "CONFLICT_INVALID_TRANSITION"

    db_session.refresh(door)
    assert door.status == DoorStatus.NOT_INSTALLED
    assert door.is_locked is False
    assert door.version == 2

    failed_event = (
        db_session.query(SyncEventORM)
        .filter(SyncEventORM.client_event_id == "stale-version-event-1")
        .one()
    )
    assert failed_event.apply_error == "CONFLICT_INVALID_TRANSITION"


def test_installer_incremental_sync_does_not_leak_unassigned_door_changes(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="No Leak Installer",
        phone="+10000000043",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="No Leak Project",
        address="3 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="No Leak Door")
    assigned_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="MINE-100",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        installed_at=None,
        is_locked=False,
    )
    unassigned_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="UNASSIGNED-100",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add_all([assigned_door, unassigned_door])
    db_session.flush()

    baseline = SyncChangeLogORM(
        created_at=datetime.now(timezone.utc),
        company_id=company_id,
        change_type=SyncChangeType.PROJECT_BASE,
        entity_id=project.id,
        project_id=project.id,
        installer_id=installer.id,
        payload={"id": str(project.id), "name": project.name},
    )
    db_session.add(baseline)
    db_session.flush()
    baseline_cursor = baseline.cursor_id

    db_session.add_all(
        [
            SyncChangeLogORM(
                created_at=datetime.now(timezone.utc),
                company_id=company_id,
                change_type=SyncChangeType.DOOR,
                entity_id=unassigned_door.id,
                project_id=project.id,
                installer_id=None,
                payload={
                    "id": str(unassigned_door.id),
                    "project_id": str(project.id),
                    "unit_label": unassigned_door.unit_label,
                    "status": "NOT_INSTALLED",
                },
            ),
            SyncChangeLogORM(
                created_at=datetime.now(timezone.utc),
                company_id=company_id,
                change_type=SyncChangeType.DOOR,
                entity_id=assigned_door.id,
                project_id=project.id,
                installer_id=installer.id,
                payload={
                    "id": str(assigned_door.id),
                    "project_id": str(project.id),
                    "unit_label": assigned_door.unit_label,
                    "status": "NOT_INSTALLED",
                },
            ),
            SyncChangeLogORM(
                created_at=datetime.now(timezone.utc),
                company_id=company_id,
                change_type=SyncChangeType.PROJECT_ADDON_PLAN,
                entity_id=project.id,
                project_id=project.id,
                installer_id=None,
                payload={
                    "kind": "addon_plan_upsert",
                    "project_id": str(project.id),
                    "plan_items": [],
                },
            ),
            SyncChangeLogORM(
                created_at=datetime.now(timezone.utc),
                company_id=company_id,
                change_type=SyncChangeType.PROJECT_ASSIGNMENTS,
                entity_id=project.id,
                project_id=project.id,
                installer_id=None,
                payload={
                    "kind": "assign_doors",
                    "project_id": str(project.id),
                    "affected_door_ids": [str(unassigned_door.id)],
                },
            ),
        ]
    )
    db_session.commit()

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": baseline_cursor,
            "ack_cursor": baseline_cursor,
            "events": [],
            "app_version": "mobile-test",
            "device_id": "device-no-leak",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reset_required"] is False

    changes = body["changes"]
    door_payload_ids = {
        row["payload"].get("id")
        for row in changes
        if row["change_type"] == SyncChangeType.DOOR.value
    }
    assert str(assigned_door.id) in door_payload_ids
    assert str(unassigned_door.id) not in door_payload_ids
    assert SyncChangeType.PROJECT_ADDON_PLAN.value in {
        row["change_type"] for row in changes
    }
    assert not any(
        row["change_type"] == SyncChangeType.PROJECT_ASSIGNMENTS.value
        and row["payload"].get("kind") == "assign_doors"
        for row in changes
    )


def test_installer_incremental_sync_does_not_replay_stale_addon_fact_after_assignment_removed(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Removed Addon Installer",
        phone="+10000000045",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="Removed Addon Project",
        address="5 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Removed Addon Door")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="REMOVED-ADDON-100",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(door)

    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Removed Project Addon",
        unit="pcs",
        default_client_price=Decimal("30.00"),
        default_installer_price=Decimal("12.00"),
        is_active=True,
        deleted_at=None,
    )
    db_session.add(addon_type)
    db_session.flush()

    baseline = SyncChangeLogORM(
        created_at=datetime.now(timezone.utc),
        company_id=company_id,
        change_type=SyncChangeType.PROJECT_BASE,
        entity_id=project.id,
        project_id=project.id,
        installer_id=installer.id,
        payload={"id": str(project.id), "name": project.name},
    )
    db_session.add(baseline)
    db_session.flush()
    baseline_cursor = baseline.cursor_id

    done_at = datetime.now(timezone.utc)
    addon_fact = ProjectAddonFactORM(
        company_id=company_id,
        project_id=project.id,
        addon_type_id=addon_type.id,
        installer_id=installer.id,
        qty_done=Decimal("1.00"),
        done_at=done_at,
        comment="old removed project fact",
        source=AddonFactSource.OFFLINE,
        client_event_id="removed-project-addon-fact",
    )
    db_session.add(addon_fact)
    db_session.flush()
    db_session.add(
        SyncChangeLogORM(
            created_at=datetime.now(timezone.utc),
            company_id=company_id,
            change_type=SyncChangeType.ADDON_FACT,
            entity_id=addon_fact.id,
            project_id=project.id,
            installer_id=installer.id,
            payload={
                "id": str(addon_fact.id),
                "project_id": str(project.id),
                "addon_type_id": str(addon_type.id),
                "installer_id": str(installer.id),
                "qty_done": "1.00",
                "done_at": done_at.isoformat(),
                "comment": "old removed project fact",
                "source": AddonFactSource.OFFLINE.value,
                "updated_at": done_at.isoformat(),
            },
        )
    )

    door.installer_id = None
    db_session.add(
        SyncChangeLogORM(
            created_at=datetime.now(timezone.utc),
            company_id=company_id,
            change_type=SyncChangeType.PROJECT_ASSIGNMENTS,
            entity_id=project.id,
            project_id=project.id,
            installer_id=installer.id,
            payload={
                "kind": "removed_from_you",
                "project_id": str(project.id),
                "affected_door_ids": [str(door.id)],
            },
        )
    )
    db_session.commit()

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": baseline_cursor,
            "ack_cursor": baseline_cursor,
            "events": [],
            "app_version": "mobile-test",
            "device_id": "device-removed-addon",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reset_required"] is False

    changes = body["changes"]
    assert any(
        row["change_type"] == SyncChangeType.PROJECT_ASSIGNMENTS.value
        and row["payload"].get("kind") == "removed_from_you"
        for row in changes
    )
    assert not any(
        row["change_type"] == SyncChangeType.ADDON_FACT.value
        and row["payload"].get("id") == str(addon_fact.id)
        for row in changes
    )


def test_installer_incremental_sync_receives_door_after_admin_assignment(
    client_admin_real_uow,
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Assignment Sync Installer",
        phone="+10000000044",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.flush()

    project = ProjectORM(
        company_id=company_id,
        name="Assignment Sync Project",
        address="4 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Assignment Sync Door")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="ASSIGN-100",
        order_number="ASSIGN-ORDER",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(door)
    db_session.flush()

    baseline = SyncChangeLogORM(
        created_at=datetime.now(timezone.utc),
        company_id=company_id,
        change_type=SyncChangeType.PROJECT_BASE,
        entity_id=project.id,
        project_id=project.id,
        installer_id=installer.id,
        payload={"id": str(project.id), "name": project.name},
    )
    db_session.add(baseline)
    db_session.commit()
    baseline_cursor = baseline.cursor_id

    assign_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/doors/{door.id}/assign-installer",
        json={"installer_id": str(installer.id)},
    )
    assert assign_resp.status_code == 200, assign_resp.text

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": baseline_cursor,
            "ack_cursor": baseline_cursor,
            "events": [],
            "app_version": "mobile-test",
            "device_id": "device-assignment",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reset_required"] is False

    door_changes = [
        row
        for row in body["changes"]
        if row["change_type"] == SyncChangeType.DOOR.value
        and row["payload"].get("id") == str(door.id)
    ]
    assert len(door_changes) == 1
    payload = door_changes[0]["payload"]
    assert payload["unit_label"] == "ASSIGN-100"
    assert payload["order_number"] == "ASSIGN-ORDER"
    assert payload["status"] == DoorStatus.NOT_INSTALLED.value


def test_imported_door_assignment_reaches_installer_sync_without_leaking_unassigned(
    client_admin_real_uow,
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Imported Assignment Installer",
        phone="+10000000045",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    project = ProjectORM(
        company_id=company_id,
        name="Imported Assignment Project",
        address="5 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add_all([installer, project])
    db_session.commit()

    door_type = make_door_type(code="import-sync-door", name="Import Sync Door")
    csv_payload = (
        "order_number,house,floor,apartment,location,marking,door_type,qty,price\n"
        "IMP-SYNC-100,A,2,201,dira,D-201,import-sync-door,1,100\n"
        "IMP-SYNC-100,A,2,202,mamad,M-202,import-sync-door,1,100\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project.id}/doors/import-file",
        json={
            "filename": "import_assignment_sync.csv",
            "content_base64": _b64(csv_payload),
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 2

    details_resp = client_admin_real_uow.get(f"/api/v1/admin/projects/{project.id}")
    assert details_resp.status_code == 200, details_resp.text
    imported_doors = sorted(
        details_resp.json()["doors"],
        key=lambda row: row["apartment_number"] or "",
    )
    assert [row["apartment_number"] for row in imported_doors] == ["201", "202"]
    assigned_door = imported_doors[0]
    unassigned_door = imported_doors[1]

    baseline = SyncChangeLogORM(
        created_at=datetime.now(timezone.utc),
        company_id=company_id,
        change_type=SyncChangeType.PROJECT_BASE,
        entity_id=project.id,
        project_id=project.id,
        installer_id=installer.id,
        payload={"id": str(project.id), "name": project.name},
    )
    db_session.add(baseline)
    db_session.commit()
    baseline_cursor = baseline.cursor_id

    assign_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/doors/{assigned_door['id']}/assign-installer",
        json={"installer_id": str(installer.id)},
    )
    assert assign_resp.status_code == 200, assign_resp.text

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": baseline_cursor,
            "ack_cursor": baseline_cursor,
            "events": [],
            "app_version": "mobile-test",
            "device_id": "device-import-assignment",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reset_required"] is False

    project_changes = [
        row
        for row in body["changes"]
        if row["change_type"] == SyncChangeType.PROJECT_BASE.value
    ]
    assert [row["payload"]["id"] for row in project_changes] == [str(project.id)]

    assignment_changes = [
        row
        for row in body["changes"]
        if row["change_type"] == SyncChangeType.PROJECT_ASSIGNMENTS.value
        and row["payload"].get("kind") == "assigned_to_you"
    ]
    assert assignment_changes
    assert assignment_changes[0]["payload"]["affected_door_ids"] == [assigned_door["id"]]

    door_changes = [
        row
        for row in body["changes"]
        if row["change_type"] == SyncChangeType.DOOR.value
    ]
    assert [row["payload"]["id"] for row in door_changes] == [assigned_door["id"]]
    payload = door_changes[0]["payload"]
    assert payload["order_number"] == "IMP-SYNC-100"
    assert payload["house_number"] == "A"
    assert payload["floor_label"] == "2"
    assert payload["apartment_number"] == "201"
    assert payload["location_code"] == "dira"
    assert payload["door_marking"] == "D-201"
    assert payload["status"] == DoorStatus.NOT_INSTALLED.value
    assert unassigned_door["id"] not in {
        row["payload"].get("id") for row in body["changes"] if isinstance(row.get("payload"), dict)
    }


def test_bulk_imported_door_assignment_reaches_installer_sync_without_leaks(
    client_admin_real_uow,
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Bulk Imported Assignment Installer",
        phone="+10000000046",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    other_installer = InstallerORM(
        company_id=company_id,
        full_name="Other Bulk Assignment Installer",
        phone="+10000000047",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=None,
    )
    project = ProjectORM(
        company_id=company_id,
        name="Bulk Imported Assignment Project",
        address="6 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add_all([installer, other_installer, project])
    db_session.commit()

    door_type = make_door_type(code="bulk-import-sync-door", name="Bulk Import Sync Door")
    csv_payload = (
        "order_number,house,floor,apartment,location,marking,door_type,qty,price\n"
        "BULK-SYNC-100,A,3,301,dira,D-301,bulk-import-sync-door,1,100\n"
        "BULK-SYNC-100,A,3,302,mamad,M-302,bulk-import-sync-door,1,100\n"
        "BULK-SYNC-100,A,3,303,fire,F-303,bulk-import-sync-door,1,100\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project.id}/doors/import-file",
        json={
            "filename": "bulk_import_assignment_sync.csv",
            "content_base64": _b64(csv_payload),
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 3

    details_resp = client_admin_real_uow.get(f"/api/v1/admin/projects/{project.id}")
    assert details_resp.status_code == 200, details_resp.text
    imported_doors = sorted(
        details_resp.json()["doors"],
        key=lambda row: row["apartment_number"] or "",
    )
    assert [row["apartment_number"] for row in imported_doors] == ["301", "302", "303"]
    target_door_ids = [imported_doors[0]["id"], imported_doors[1]["id"]]
    other_door_id = imported_doors[2]["id"]

    baseline = SyncChangeLogORM(
        created_at=datetime.now(timezone.utc),
        company_id=company_id,
        change_type=SyncChangeType.PROJECT_BASE,
        entity_id=project.id,
        project_id=project.id,
        installer_id=installer.id,
        payload={"id": str(project.id), "name": project.name},
    )
    db_session.add(baseline)
    db_session.commit()
    baseline_cursor = baseline.cursor_id

    bulk_assign_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/doors/bulk-assign-installer",
        json={"door_ids": target_door_ids, "installer_id": str(installer.id)},
    )
    assert bulk_assign_resp.status_code == 200, bulk_assign_resp.text
    assert bulk_assign_resp.json()["assigned"] == 2
    assert bulk_assign_resp.json()["skipped"] == 0
    assert bulk_assign_resp.json()["assigned_door_ids"] == target_door_ids

    other_assign_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/doors/{other_door_id}/assign-installer",
        json={"installer_id": str(other_installer.id)},
    )
    assert other_assign_resp.status_code == 200, other_assign_resp.text

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": baseline_cursor,
            "ack_cursor": baseline_cursor,
            "events": [],
            "app_version": "mobile-test",
            "device_id": "device-bulk-import-assignment",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reset_required"] is False

    project_changes = [
        row
        for row in body["changes"]
        if row["change_type"] == SyncChangeType.PROJECT_BASE.value
    ]
    assert [row["payload"]["id"] for row in project_changes] == [str(project.id)]

    assignment_changes = [
        row
        for row in body["changes"]
        if row["change_type"] == SyncChangeType.PROJECT_ASSIGNMENTS.value
        and row["payload"].get("kind") == "assigned_to_you"
    ]
    assert len(assignment_changes) == 1
    assert assignment_changes[0]["payload"]["affected_door_ids"] == target_door_ids

    door_changes = [
        row
        for row in body["changes"]
        if row["change_type"] == SyncChangeType.DOOR.value
    ]
    assert [row["payload"]["id"] for row in door_changes] == target_door_ids
    assert {row["payload"]["apartment_number"] for row in door_changes} == {"301", "302"}
    assert other_door_id not in {
        row["payload"].get("id") for row in body["changes"] if isinstance(row.get("payload"), dict)
    }


def test_bulk_reassignment_notifies_previous_installer_removed_from_you(
    client_admin_real_uow,
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    previous_installer = InstallerORM(
        company_id=company_id,
        full_name="Previous Bulk Assignment Installer",
        phone="+10000000048",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    next_installer = InstallerORM(
        company_id=company_id,
        full_name="Next Bulk Assignment Installer",
        phone="+10000000049",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=None,
    )
    project = ProjectORM(
        company_id=company_id,
        name="Bulk Reassignment Project",
        address="7 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add_all([previous_installer, next_installer, project])
    db_session.commit()

    door_type = make_door_type(code="bulk-reassign-sync-door", name="Bulk Reassign Sync Door")
    csv_payload = (
        "order_number,house,floor,apartment,location,marking,door_type,qty,price\n"
        "REASSIGN-SYNC-100,A,4,401,dira,D-401,bulk-reassign-sync-door,1,100\n"
        "REASSIGN-SYNC-100,A,4,402,mamad,M-402,bulk-reassign-sync-door,1,100\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project.id}/doors/import-file",
        json={
            "filename": "bulk_reassignment_sync.csv",
            "content_base64": _b64(csv_payload),
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 2

    details_resp = client_admin_real_uow.get(f"/api/v1/admin/projects/{project.id}")
    assert details_resp.status_code == 200, details_resp.text
    imported_doors = sorted(
        details_resp.json()["doors"],
        key=lambda row: row["apartment_number"] or "",
    )
    door_ids = [row["id"] for row in imported_doors]
    assert len(door_ids) == 2

    initial_assign_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/doors/bulk-assign-installer",
        json={"door_ids": door_ids, "installer_id": str(previous_installer.id)},
    )
    assert initial_assign_resp.status_code == 200, initial_assign_resp.text
    assert initial_assign_resp.json()["assigned"] == 2

    baseline = SyncChangeLogORM(
        created_at=datetime.now(timezone.utc),
        company_id=company_id,
        change_type=SyncChangeType.PROJECT_BASE,
        entity_id=project.id,
        project_id=project.id,
        installer_id=previous_installer.id,
        payload={"id": str(project.id), "name": project.name},
    )
    db_session.add(baseline)
    db_session.commit()
    baseline_cursor = baseline.cursor_id

    reassign_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/doors/bulk-assign-installer",
        json={"door_ids": door_ids, "installer_id": str(next_installer.id)},
    )
    assert reassign_resp.status_code == 200, reassign_resp.text
    assert reassign_resp.json()["assigned"] == 2
    assert reassign_resp.json()["assigned_door_ids"] == door_ids

    resp = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": baseline_cursor,
            "ack_cursor": baseline_cursor,
            "events": [],
            "app_version": "mobile-test",
            "device_id": "device-bulk-reassignment",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reset_required"] is False

    removed_changes = [
        row
        for row in body["changes"]
        if row["change_type"] == SyncChangeType.PROJECT_ASSIGNMENTS.value
        and row["payload"].get("kind") == "removed_from_you"
    ]
    assert len(removed_changes) == 1
    assert removed_changes[0]["payload"]["affected_door_ids"] == door_ids

    assert [
        row for row in body["changes"] if row["change_type"] == SyncChangeType.DOOR.value
    ] == []
