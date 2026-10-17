from __future__ import annotations

import base64
from copy import deepcopy
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.modules.addons.domain.enums import AddonFactSource
from app.modules.addons.infrastructure.models import (
    AddonTypeORM,
    ProjectAddonFactORM,
    ProjectAddonPlanORM,
)
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.doors.infrastructure.history_models import DoorStatusHistoryORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.projects.application.use_cases import ProjectUseCases
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.modules.sync.application.service import InstallerSyncService
from app.modules.sync.domain.enums import SyncChangeType, SyncEventType
from app.modules.sync.infrastructure.models import SyncChangeLogORM, SyncEventORM
from app.modules.sync.infrastructure.repositories import SyncEventRepository
from app.shared.domain.errors import ValidationError
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


@pytest.fixture()
def sync_replay_case(client_raw, db_session, company_id, make_user, make_installer, make_door_type):
    user = make_user(password="Sync-replay-test-2026!")
    installer = make_installer(full_name="Replay test installer")
    installer.user_id = user.id
    door_type = make_door_type()
    project = ProjectORM(
        company_id=company_id, name="Replay test tower", address="101 Test Street", status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()
    door = DoorORM(
        company_id=company_id, project_id=project.id, door_type_id=door_type.id,
        unit_label="REPLAY-101", our_price=Decimal("1000.00"),
        installer_rate_snapshot=Decimal("250.00"), installer_id=installer.id,
        status=DoorStatus.IN_PROGRESS, is_locked=False, version=0,
    )
    db_session.add(door)
    db_session.commit()
    login = client_raw.post("/api/v1/auth/login", json={
        "company_id": str(company_id), "email": user.email,
        "password": "Sync-replay-test-2026!", "device_id": "sync-replay-test",
    })
    assert login.status_code == 200, login.text
    return {
        "client": client_raw, "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
        "company_id": company_id, "door": door, "installer_id": installer.id,
        "event": {
            "client_event_id": "lost-response-installation", "type": "DOOR_SET_STATUS",
            "project_id": str(project.id), "happened_at": "2026-09-11T10:00:00Z",
            "payload": {"door_id": str(door.id), "status": "INSTALLED", "previous_version": 0},
        },
    }


def _post_replay_event(case, event):
    response = case["client"].post("/api/v1/installer/sync", headers=case["headers"], json={
        "since_cursor": 0, "ack_cursor": 0, "device_id": "sync-replay-test",
        "events": [event],
    })
    assert response.status_code == 200, response.text
    return response.json()


def _assert_one_replay_installation(case, db_session):
    door = case["door"]
    db_session.refresh(door)
    assert (door.status, door.is_locked, door.version) == (DoorStatus.INSTALLED, True, 1)
    work = db_session.query(CompletedWorkORM).filter(CompletedWorkORM.door_id == door.id).one()
    assert work.installer_id == case["installer_id"]
    assert work.entry_type == "ORIGINAL"
    assert work.quantity == Decimal("1.00")
    assert work.amount_snapshot == work.rate_snapshot == Decimal("250.00")
    assert db_session.query(DoorStatusHistoryORM).filter(DoorStatusHistoryORM.door_id == door.id).count() == 1
    assert db_session.query(SyncEventORM).filter(SyncEventORM.company_id == case["company_id"]).count() == 1
    assert db_session.query(SyncChangeLogORM).filter(SyncChangeLogORM.entity_id == door.id).count() == 1


@pytest.mark.parametrize("transport", ["snapshot", "batch"])
@pytest.mark.parametrize("timestamp,expected_rate", [
    ("2026-08-31T20:59:00Z", "250.00"),
    ("2026-08-31T23:59:00+03:00", "250.00"),
    ("2026-08-31T20:59:00", "250.00"),
    (None, "450.00"),
    ("2099-01-01T00:00:00Z", "450.00"),
])
def test_offline_completion_time_controls_period_and_rate(
    sync_replay_case, db_session, monkeypatch, transport, timestamp, expected_rate,
):
    from app.modules.doors.application import completion, use_cases

    received_at = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(completion, "utcnow", lambda: received_at)
    monkeypatch.setattr(use_cases, "utcnow", lambda: received_at)
    case = sync_replay_case
    door = case["door"]
    door.installer_rate_snapshot = None
    for effective_from, price in [
        (datetime(2026, 1, 1, tzinfo=timezone.utc), "250.00"),
        (datetime(2026, 8, 31, 21, tzinfo=timezone.utc), "450.00"),
    ]:
        db_session.add(InstallerRateORM(
            company_id=case["company_id"], installer_id=case["installer_id"],
            door_type_id=door.door_type_id, effective_from=effective_from,
            price=Decimal(price),
        ))
    db_session.commit()
    event = deepcopy(case["event"])
    event["happened_at"] = timestamp
    if transport == "snapshot":
        send = lambda: _post_replay_event(case, event)
    else:
        item = {
            "id": str(uuid.uuid4()), "entity_type": "door", "entity_id": str(door.id),
            "operation_type": event["type"], "project_id": event["project_id"],
            "payload": event["payload"], "base_version": 0, "happened_at": timestamp,
        }

        def send():
            response = case["client"].post(
                "/api/v1/installer/sync-queue/batch", headers=case["headers"],
                json={"device_id": "completion-time-test", "items": [item]},
            )
            assert response.status_code == 200, response.text
            return response.json()

    for _ in range(2):
        result = send()
        if transport == "snapshot":
            assert result["acks"][0]["ok"] is True, result
        else:
            assert result["results"][0]["status"] == "APPLIED", result
    expected_at = (
        datetime(2026, 8, 31, 20, 59, tzinfo=timezone.utc)
        if expected_rate == "250.00" else received_at
    )
    db_session.refresh(door)
    work = db_session.query(CompletedWorkORM).filter(CompletedWorkORM.door_id == door.id).one()
    assert work.completed_at == door.installed_at == expected_at
    assert work.rate_snapshot == work.amount_snapshot == Decimal(expected_rate)
    assert door.version == 1


@pytest.mark.parametrize("timestamp", [
    "2026-09-11T10:00:00Z", "2026-09-11T13:00:00+03:00", "2026-09-11T10:00:00", None,
])
def test_sync_lost_response_replay_keeps_one_installation_and_accrual(sync_replay_case, db_session, timestamp):
    case = sync_replay_case
    if timestamp is None:
        case["event"].pop("happened_at")
    elif timestamp == "2026-09-11T10:00:00":
        case["event"]["happened_at"] = timestamp
    # The first response is deliberately not acknowledged by the next request.
    first = _post_replay_event(case, case["event"])
    assert first["acks"][0]["ok"] is True
    assert first["acks"][0]["applied"] is True
    replay = deepcopy(case["event"])
    replay["payload"] = dict(reversed(list(replay["payload"].items())))
    if timestamp is not None:
        replay["happened_at"] = timestamp
    for _ in range(2):
        result = _post_replay_event(case, replay)
        assert result["acks"] == [{
            "client_event_id": replay["client_event_id"], "ok": True, "applied": False, "error": None,
        }]
    _assert_one_replay_installation(case, db_session)


@pytest.mark.parametrize("race_lookup", [False, True])
@pytest.mark.parametrize("changed_field", ["door", "project", "type", "payload", "time", "missing_time"])
def test_sync_reused_event_id_does_not_ack_different_work(
    sync_replay_case, db_session, monkeypatch, changed_field, race_lookup,
):
    case = sync_replay_case
    assert _post_replay_event(case, case["event"])["acks"][0]["ok"] is True
    replay = deepcopy(case["event"])
    if changed_field == "door":
        replay["payload"]["door_id"] = str(uuid.uuid4())
    elif changed_field == "project":
        replay["project_id"] = str(uuid.uuid4())
    elif changed_field == "type":
        replay["type"] = "ISSUE_CREATE"
    elif changed_field == "payload":
        replay["payload"]["comment"] = "A different completion"
    elif changed_field == "time":
        replay["happened_at"] = "2026-09-11T10:01:00Z"
    else:
        replay.pop("happened_at")

    if race_lookup:
        original_get = SyncEventRepository.get_by_client_event
        lookups = 0

        def miss_first_lookup(self, **kwargs):
            nonlocal lookups
            lookups += 1
            return None if lookups == 1 else original_get(self, **kwargs)

        monkeypatch.setattr(SyncEventRepository, "get_by_client_event", miss_first_lookup)

    result = _post_replay_event(case, replay)
    assert result["acks"] == [{
        "client_event_id": replay["client_event_id"], "ok": False, "applied": False,
        "error": "CONFLICT_INVALID_TRANSITION",
    }]
    _assert_one_replay_installation(case, db_session)
    stored = db_session.query(SyncEventORM).filter(SyncEventORM.company_id == case["company_id"]).one()
    assert stored.payload == case["event"]["payload"]
    assert stored.apply_error is None
    assert _post_replay_event(case, case["event"])["acks"][0]["ok"] is True


@pytest.mark.parametrize("deleted", [True, False], ids=["deleted-project", "active-project"])
@pytest.mark.parametrize("operation", [
    "sync-install", "sync-not-installed", "sync-issue", "batch-install",
    "online-install", "online-not-installed", "online-status", "online-issue",
])
def test_installer_actions_respect_project_deletion(
    sync_replay_case, db_session, make_reason, deleted, operation,
):
    case = sync_replay_case
    door = case["door"]
    project_id = door.project_id
    event = deepcopy(case["event"])
    reason = make_reason()
    if "not-installed" in operation:
        event["payload"].update(status="NOT_INSTALLED", reason_id=str(reason.id))
    elif "issue" in operation:
        event["type"] = "ISSUE_CREATE"
        event["payload"] = {"door_id": str(door.id), "title": "Opening is blocked"}

    if deleted:
        with SqlAlchemyUnitOfWork() as uow:
            ProjectUseCases.delete_project(uow, company_id=case["company_id"], project_id=project_id)

    if operation.startswith("sync-"):
        result = _post_replay_event(case, event)
        assert result["acks"] == [{
            "client_event_id": event["client_event_id"], "ok": not deleted, "applied": not deleted,
            "error": "CONFLICT_ASSIGNMENT_CHANGED" if deleted else None,
        }]
        stored = db_session.query(SyncEventORM).filter(SyncEventORM.company_id == case["company_id"]).one()
        assert stored.payload == event["payload"]
    elif operation == "batch-install":
        response = case["client"].post("/api/v1/installer/sync-queue/batch", headers=case["headers"], json={
            "device_id": "deleted-project-check", "items": [{
                "id": str(uuid.uuid4()), "entity_type": "door", "entity_id": str(door.id),
                "project_id": str(project_id), "operation_type": "DOOR_SET_STATUS",
                "payload": event["payload"], "base_version": 0,
            }],
        })
        assert response.status_code == 200, response.text
        result = response.json()["results"][0]
        assert result["status"] == ("CONFLICT" if deleted else "APPLIED"), result
        assert result["conflict_code"] == ("CONFLICT_ASSIGNMENT_CHANGED" if deleted else None)
    else:
        route = f"/api/v1/installer/doors/{door.id}"
        if operation == "online-status":
            response = case["client"].patch(route + "/status", headers=case["headers"], json={"status": "INSTALLED"})
        elif operation == "online-issue":
            response = case["client"].post("/api/v1/installer/issues", headers=case["headers"], json=event["payload"])
        else:
            suffix = operation.removeprefix("online-")
            response = case["client"].post(route + "/" + suffix, headers=case["headers"],
                json={"reason_id": str(reason.id)} if suffix == "not-installed" else None)
        expected = 404 if deleted else 201 if operation == "online-issue" else 200
        assert response.status_code == expected, response.text

    db_session.expire_all()
    db_session.refresh(door)
    works = db_session.query(CompletedWorkORM).filter(CompletedWorkORM.door_id == door.id).all()
    history_count = db_session.query(DoorStatusHistoryORM).filter(DoorStatusHistoryORM.door_id == door.id).count()
    issue_count = db_session.query(IssueORM).filter(IssueORM.door_id == door.id).count()
    project = db_session.get(ProjectORM, project_id)
    assert (project.deleted_at is not None) == deleted
    if deleted:
        assert (door.status, door.is_locked, door.version) == (DoorStatus.IN_PROGRESS, False, 0)
        assert works == []
        assert history_count == issue_count == 0
    else:
        assert door.version == history_count == 1
        if "not-installed" in operation or "issue" in operation:
            assert works == []
            assert issue_count == 1
        else:
            assert door.status == DoorStatus.INSTALLED
            assert len(works) == 1
            assert works[0].amount_snapshot == Decimal("250.00")


@pytest.mark.parametrize("deleted", [False, True])
def test_installer_issue_access_respects_project_deletion(sync_replay_case, db_session, deleted):
    case = sync_replay_case
    client, headers = case["client"], case["headers"]
    created = client.post("/api/v1/installer/issues", headers=headers, json={
        "door_id": str(case["door"].id), "title": "Opening blocked", "details": "Original comment",
    })
    assert created.status_code == 201, created.text
    issue_id = created.json()["id"]
    if deleted:
        with SqlAlchemyUnitOfWork() as deletion:
            ProjectUseCases.delete_project(
                deletion, company_id=case["company_id"], project_id=case["door"].project_id,
            )

    listing = client.get("/api/v1/installer/issues", headers=headers)
    assert listing.status_code == 200, listing.text
    assert {item["id"] for item in listing.json()["items"]} == (set() if deleted else {issue_id})
    media = client.get(f"/api/v1/installer/issues/{issue_id}/media", headers=headers)
    assert media.status_code == (404 if deleted else 200), media.text
    updated = client.patch(f"/api/v1/installer/issues/{issue_id}", headers=headers, json={"comment": "Updated comment"})
    assert updated.status_code == (404 if deleted else 200), updated.text
    db_session.expire_all()
    issue = db_session.get(IssueORM, uuid.UUID(issue_id))
    assert issue.details == ("Original comment" if deleted else "Updated comment")


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
        client_happened_at=None,
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


def test_installer_sync_server_fault_is_retryable_and_not_sticky(sync_replay_case, db_session, monkeypatch):
    """A fault inside the server (not a decision about the work) must not become a
    permanent conflict for that client_event_id, and must not leak its message."""
    case = sync_replay_case
    original = InstallerSyncService._apply_door_set_status

    def _server_fault(uow, **kwargs):
        raise RuntimeError("database connection reset: internal detail")

    monkeypatch.setattr(InstallerSyncService, "_apply_door_set_status", staticmethod(_server_fault))
    first = _post_replay_event(case, case["event"])
    assert first["acks"] == [{
        "client_event_id": case["event"]["client_event_id"], "ok": False, "applied": False, "error": "SERVER_ERROR",
    }]
    assert "internal detail" not in str(first)
    assert db_session.query(SyncEventORM).filter(SyncEventORM.company_id == case["company_id"]).count() == 0

    monkeypatch.setattr(InstallerSyncService, "_apply_door_set_status", staticmethod(original))
    replay = _post_replay_event(case, case["event"])
    assert replay["acks"] == [{
        "client_event_id": case["event"]["client_event_id"], "ok": True, "applied": True, "error": None,
    }]
    _assert_one_replay_installation(case, db_session)


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


def test_project_delete_removes_it_from_incremental_and_cold_sync(
    client_admin_real_uow,
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Deleted Project Installer",
        phone="+10000000050",
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
        name="Deleted Sync Project",
        address="8 Snapshot Street",
        status=ProjectStatus.OK,
    )
    db_session.add_all([installer, project])
    db_session.flush()

    door_type = make_door_type(
        code="deleted-project-sync-door",
        name="Deleted Project Sync Door",
    )
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="DELETE-100",
        order_number="DELETE-ORDER",
        our_price="100.00",
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
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

    delete_response = client_admin_real_uow.delete(
        f"/api/v1/admin/projects/{project.id}"
    )
    assert delete_response.status_code == 200, delete_response.text

    incremental_response = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": baseline.cursor_id,
            "ack_cursor": baseline.cursor_id,
            "events": [],
            "app_version": "mobile-test",
            "device_id": "device-project-delete",
        },
    )
    assert incremental_response.status_code == 200, incremental_response.text
    incremental = incremental_response.json()
    removed = [
        change
        for change in incremental["changes"]
        if change["change_type"] == SyncChangeType.PROJECT_ASSIGNMENTS.value
        and change["payload"].get("kind") == "removed_from_you"
    ]
    assert len(removed) == 1
    assert removed[0]["payload"]["project_id"] == str(project.id)
    assert removed[0]["payload"]["affected_door_ids"] == [str(door.id)]

    cold_response = client_installer.post(
        "/api/v1/installer/sync",
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [],
            "app_version": "mobile-test",
            "device_id": "device-project-delete-cold",
        },
    )
    assert cold_response.status_code == 200, cold_response.text
    cold = cold_response.json()
    assert cold["reset_required"] is True
    assert str(project.id) not in {
        row["id"] for row in cold["snapshot"]["projects"]
    }
    assert str(door.id) not in {
        row["id"] for row in cold["snapshot"]["doors"]
    }
