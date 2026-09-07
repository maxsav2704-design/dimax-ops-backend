from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, require_installer
from app.main import create_app
from app.modules.addons.domain.enums import AddonFactSource
from app.modules.addons.infrastructure.models import (
    AddonTypeORM,
    ProjectAddonFactORM,
    ProjectAddonPlanORM,
)
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.history_models import DoorStatusHistoryORM
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.sync.application.service import InstallerSyncService
from app.modules.sync.infrastructure.models import SyncChangeLogORM, SyncQueueItemORM
from app.shared.domain.errors import Unauthorized, ValidationError


@pytest.fixture()
def installer_sync_batch_client(installer_user: CurrentUser, db_session):
    installer = InstallerORM(
        company_id=installer_user.company_id,
        full_name="Batch Installer",
        phone=f"+1555{uuid.uuid4().hex[:8]}",
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
        yield test_client, installer.id, installer_user

    app.dependency_overrides.clear()


def _make_project(*, company_id: uuid.UUID, name: str) -> ProjectORM:
    return ProjectORM(
        company_id=company_id,
        name=name,
        address="1 Sync Street",
        code=f"SYNC-{uuid.uuid4().hex[:6].upper()}",
        status=ProjectStatus.OK,
        lifecycle_status="ACTIVE",
        health_status="NORMAL",
    )


def _make_door(
    *,
    company_id: uuid.UUID,
    project_id: uuid.UUID,
    door_type_id: uuid.UUID,
    installer_id: uuid.UUID | None,
    status: DoorStatus,
    version: int,
) -> DoorORM:
    return DoorORM(
        company_id=company_id,
        project_id=project_id,
        door_type_id=door_type_id,
        unit_label=f"SYNC-{uuid.uuid4().hex[:4].upper()}",
        door_code=f"D-{uuid.uuid4().hex[:4].upper()}",
        our_price=Decimal("100.00"),
        status=status,
        installer_id=installer_id,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
        version=version,
        surcharge_pct=Decimal("100.00"),
    )


def _batch_item(
    *,
    project_id: uuid.UUID,
    door_id: uuid.UUID,
    status: str,
    base_version: int,
    reason_id: uuid.UUID | None = None,
    comment: str | None = None,
):
    payload = {
        "door_id": str(door_id),
        "status": status,
    }
    if reason_id is not None:
        payload["reason_id"] = str(reason_id)
    if comment is not None:
        payload["comment"] = comment

    return {
        "id": str(uuid.uuid4()),
        "entity_type": "door",
        "entity_id": str(door_id),
        "operation_type": "DOOR_SET_STATUS",
        "project_id": str(project_id),
        "payload": payload,
        "base_version": base_version,
        "happened_at": datetime.now(timezone.utc).isoformat(),
    }


def _addon_batch_item(
    *,
    project_id: uuid.UUID,
    addon_type_id: uuid.UUID,
    qty_done: str,
) -> dict:
    item_id = uuid.uuid4()
    return {
        "id": str(item_id),
        "entity_type": "addon_fact",
        "entity_id": str(item_id),
        "operation_type": "ADDON_FACT_CREATE",
        "project_id": str(project_id),
        "payload": {
            "addon_type_id": str(addon_type_id),
            "qty_done": qty_done,
            "comment": "offline addon",
        },
        "base_version": 0,
        "happened_at": datetime.now(timezone.utc).isoformat(),
    }


def test_sync_queue_batch_applies_item_and_marks_queue_row_synced(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, user = installer_sync_batch_client
    project = _make_project(company_id=company_id, name="Batch Apply")
    door_type = make_door_type(name="Batch Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=installer_id,
        status=DoorStatus.NOT_INSTALLED,
        version=0,
    )
    db_session.add(door)
    db_session.commit()

    item = _batch_item(
        project_id=project.id,
        door_id=door.id,
        status="IN_PROGRESS",
        base_version=0,
    )
    resp = client.post(
        "/api/v1/installer/sync-queue/batch",
        json={
            "device_id": "sync-batch-device",
            "app_version": "mobile-batch",
            "items": [item],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["status"] == "APPLIED"
    assert body["results"][0]["new_version"] == 1
    assert body["results"][0]["conflict_code"] is None

    db_session.refresh(door)
    assert door.status == DoorStatus.IN_PROGRESS
    assert door.version == 1

    queue_row = (
        db_session.query(SyncQueueItemORM)
        .filter(
            SyncQueueItemORM.company_id == company_id,
            SyncQueueItemORM.user_id == user.id,
        )
        .one()
    )
    assert queue_row.device_id == "sync-batch-device"
    assert queue_row.project_id == project.id
    assert queue_row.base_version == 0
    assert queue_row.status == "APPLIED"
    assert queue_row.conflict_code is None
    assert queue_row.synced_at is not None

    queue_resp = client.get("/api/v1/installer/sync-queue")
    assert queue_resp.status_code == 200, queue_resp.text
    queue_body = queue_resp.json()
    listed_item = next(x for x in queue_body["items"] if x["id"] == item["id"])
    assert listed_item["project_id"] == str(project.id)


def test_sync_queue_batch_replays_applied_door_item_without_conflict(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, user = installer_sync_batch_client
    project = _make_project(company_id=company_id, name="Batch Door Replay")
    door_type = make_door_type(name="Batch Replay Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=installer_id,
        status=DoorStatus.NOT_INSTALLED,
        version=0,
    )
    db_session.add(door)
    db_session.commit()

    item = _batch_item(
        project_id=project.id,
        door_id=door.id,
        status="IN_PROGRESS",
        base_version=0,
    )
    payload = {
        "device_id": "sync-batch-device",
        "app_version": "mobile-batch",
        "items": [item],
    }

    first_resp = client.post("/api/v1/installer/sync-queue/batch", json=payload)
    assert first_resp.status_code == 200, first_resp.text
    assert first_resp.json()["results"][0]["status"] == "APPLIED"

    second_resp = client.post("/api/v1/installer/sync-queue/batch", json=payload)
    assert second_resp.status_code == 200, second_resp.text
    second_result = second_resp.json()["results"][0]
    assert second_result["status"] == "APPLIED"
    assert second_result["new_version"] == 1
    assert second_result["conflict_code"] is None

    db_session.refresh(door)
    assert door.status == DoorStatus.IN_PROGRESS
    assert door.version == 1

    queue_row = (
        db_session.query(SyncQueueItemORM)
        .filter(
            SyncQueueItemORM.company_id == company_id,
            SyncQueueItemORM.user_id == user.id,
            SyncQueueItemORM.id == uuid.UUID(item["id"]),
        )
        .one()
    )
    assert queue_row.status == "APPLIED"
    assert queue_row.conflict_code is None
    assert queue_row.synced_at is not None

    changes = (
        db_session.query(SyncChangeLogORM)
        .filter(
            SyncChangeLogORM.company_id == company_id,
            SyncChangeLogORM.entity_id == door.id,
        )
        .all()
    )
    assert len(changes) == 1
    history = (
        db_session.query(DoorStatusHistoryORM)
        .filter(DoorStatusHistoryORM.door_id == door.id)
        .one()
    )
    assert history.source == "OFFLINE_SYNC"
    assert history.to_status == DoorStatus.IN_PROGRESS.value


def test_sync_queue_batch_not_installed_returns_incremented_version_and_payload(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
    make_reason,
):
    client, installer_id, _user = installer_sync_batch_client
    project = _make_project(company_id=company_id, name="Batch Not Installed")
    door_type = make_door_type(name="Batch Not Installed Door")
    reason = make_reason(code="BATCH_BLOCKED", name="Batch blocked")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=installer_id,
        status=DoorStatus.IN_PROGRESS,
        version=3,
    )
    db_session.add(door)
    db_session.commit()

    resp = client.post(
        "/api/v1/installer/sync-queue/batch",
        json={
            "device_id": "sync-batch-device",
            "app_version": "mobile-batch",
            "items": [
                _batch_item(
                    project_id=project.id,
                    door_id=door.id,
                    status="NOT_INSTALLED",
                    base_version=3,
                    reason_id=reason.id,
                    comment="Opening blocked",
                )
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "APPLIED"
    assert result["new_version"] == 4
    assert result["conflict_code"] is None

    db_session.refresh(door)
    assert door.status == DoorStatus.NOT_INSTALLED
    assert door.reason_id == reason.id
    assert door.comment == "Opening blocked"
    assert door.version == 4

    change = (
        db_session.query(SyncChangeLogORM)
        .filter(
            SyncChangeLogORM.company_id == company_id,
            SyncChangeLogORM.entity_id == door.id,
        )
        .order_by(SyncChangeLogORM.cursor_id.desc())
        .first()
    )
    assert change is not None
    assert change.payload["status"] == "NOT_INSTALLED"
    assert change.payload["version"] == 4


def test_sync_queue_batch_addon_fact_creates_single_earnings_ledger_entry(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, user = installer_sync_batch_client
    project = _make_project(company_id=company_id, name="Batch Addon")
    door_type = make_door_type(name="Batch Addon Door")
    db_session.add(project)
    db_session.flush()
    db_session.add(
        _make_door(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            installer_id=installer_id,
            status=DoorStatus.NOT_INSTALLED,
            version=0,
        )
    )
    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Batch seal",
        unit="pcs",
        default_client_price=Decimal("20.00"),
        default_installer_price=Decimal("7.50"),
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
            qty_planned=Decimal("3.00"),
            client_price=Decimal("20.00"),
            installer_price=Decimal("7.50"),
        )
    )
    db_session.commit()

    item = _addon_batch_item(
        project_id=project.id,
        addon_type_id=addon_type.id,
        qty_done="2.00",
    )
    payload = {
        "device_id": "sync-batch-device",
        "app_version": "mobile-batch",
        "items": [item],
    }
    first_resp = client.post("/api/v1/installer/sync-queue/batch", json=payload)
    assert first_resp.status_code == 200, first_resp.text
    assert first_resp.json()["results"][0]["status"] == "APPLIED"

    second_resp = client.post("/api/v1/installer/sync-queue/batch", json=payload)
    assert second_resp.status_code == 200, second_resp.text
    assert second_resp.json()["results"][0]["status"] == "APPLIED"

    facts = (
        db_session.query(ProjectAddonFactORM)
        .filter(
            ProjectAddonFactORM.company_id == company_id,
            ProjectAddonFactORM.installer_id == installer_id,
            ProjectAddonFactORM.client_event_id == item["id"],
        )
        .all()
    )
    assert len(facts) == 1

    ledger_rows = (
        db_session.query(CompletedWorkORM)
        .filter(
            CompletedWorkORM.company_id == company_id,
            CompletedWorkORM.installer_id == installer_id,
            CompletedWorkORM.work_kind == "ADDON",
        )
        .all()
    )
    assert len(ledger_rows) == 1
    assert ledger_rows[0].addon_fact_id == facts[0].id
    assert ledger_rows[0].quantity == Decimal("2.00")
    assert ledger_rows[0].rate_snapshot == Decimal("7.50")
    assert ledger_rows[0].amount_snapshot == Decimal("15.00")

    change = (
        db_session.query(SyncChangeLogORM)
        .filter(
            SyncChangeLogORM.company_id == company_id,
            SyncChangeLogORM.entity_id == facts[0].id,
        )
        .one()
    )
    assert change.payload["source"] == AddonFactSource.OFFLINE.value
    assert "client_price" not in change.payload
    assert "installer_price" not in change.payload
    assert "amount_snapshot" not in change.payload

    queue_row = (
        db_session.query(SyncQueueItemORM)
        .filter(
            SyncQueueItemORM.company_id == company_id,
            SyncQueueItemORM.user_id == user.id,
            SyncQueueItemORM.id == uuid.UUID(item["id"]),
        )
        .one()
    )
    assert queue_row.status == "APPLIED"
    assert queue_row.project_id == project.id
    assert queue_row.synced_at is not None


def test_sync_queue_batch_rejects_addon_fact_for_unassigned_project(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
    make_installer,
):
    client, _installer_id, user = installer_sync_batch_client
    other_installer = make_installer(
        full_name="Other Addon Sync",
        phone="+972500001113",
    )
    project = _make_project(company_id=company_id, name="Batch Addon Foreign")
    door_type = make_door_type(name="Batch Addon Foreign Door")
    db_session.add(project)
    db_session.flush()
    db_session.add(
        _make_door(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            installer_id=other_installer.id,
            status=DoorStatus.NOT_INSTALLED,
            version=0,
        )
    )
    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Foreign batch seal",
        unit="pcs",
        default_client_price=Decimal("20.00"),
        default_installer_price=Decimal("7.50"),
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
            qty_planned=Decimal("3.00"),
            client_price=Decimal("20.00"),
            installer_price=Decimal("7.50"),
        )
    )
    db_session.commit()

    item = _addon_batch_item(
        project_id=project.id,
        addon_type_id=addon_type.id,
        qty_done="2.00",
    )
    resp = client.post(
        "/api/v1/installer/sync-queue/batch",
        json={
            "device_id": "sync-batch-device-unassigned-addon",
            "app_version": "mobile-batch",
            "items": [item],
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "CONFLICT"
    assert result["conflict_code"] == "CONFLICT_ASSIGNMENT_CHANGED"
    assert result["new_version"] is None

    assert (
        db_session.query(ProjectAddonFactORM)
        .filter(
            ProjectAddonFactORM.company_id == company_id,
            ProjectAddonFactORM.client_event_id == item["id"],
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

    queue_row = (
        db_session.query(SyncQueueItemORM)
        .filter(
            SyncQueueItemORM.company_id == company_id,
            SyncQueueItemORM.user_id == user.id,
            SyncQueueItemORM.id == uuid.UUID(item["id"]),
        )
        .one()
    )
    assert queue_row.status == "CONFLICT"
    assert queue_row.conflict_code == "CONFLICT_ASSIGNMENT_CHANGED"


def test_sync_queue_batch_returns_conflict_invalid_transition_for_stale_version(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, user = installer_sync_batch_client
    project = _make_project(company_id=company_id, name="Batch Stale")
    door_type = make_door_type(name="Batch Stale Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=installer_id,
        status=DoorStatus.IN_PROGRESS,
        version=1,
    )
    db_session.add(door)
    db_session.commit()

    item = _batch_item(
        project_id=project.id,
        door_id=door.id,
        status="IN_PROGRESS",
        base_version=0,
    )
    resp = client.post(
        "/api/v1/installer/sync-queue/batch",
        json={
            "device_id": "sync-batch-device",
            "items": [item],
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "CONFLICT"
    assert result["conflict_code"] == "CONFLICT_INVALID_TRANSITION"
    assert result["new_version"] is None

    queue_row = (
        db_session.query(SyncQueueItemORM)
        .filter(
            SyncQueueItemORM.company_id == company_id,
            SyncQueueItemORM.user_id == user.id,
            SyncQueueItemORM.id == uuid.UUID(item["id"]),
        )
        .one()
    )
    assert queue_row.status == "CONFLICT"
    assert queue_row.conflict_code == "CONFLICT_INVALID_TRANSITION"


def test_sync_queue_batch_rejects_install_without_positive_rate(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, user = installer_sync_batch_client
    project = _make_project(company_id=company_id, name="Batch Missing Rate")
    door_type = make_door_type(name="Batch Missing Rate Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=installer_id,
        status=DoorStatus.IN_PROGRESS,
        version=1,
    )
    db_session.add(door)
    db_session.commit()

    item = _batch_item(
        project_id=project.id,
        door_id=door.id,
        status="INSTALLED",
        base_version=1,
    )
    resp = client.post(
        "/api/v1/installer/sync-queue/batch",
        json={"device_id": "sync-batch-missing-rate", "items": [item]},
    )

    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "CONFLICT"
    assert result["conflict_code"] == "CONFLICT_INVALID_TRANSITION"
    assert result["new_version"] is None
    db_session.expire_all()
    persisted = db_session.get(DoorORM, door.id)
    assert persisted is not None
    assert persisted.status == DoorStatus.IN_PROGRESS
    assert persisted.version == 1
    assert persisted.is_locked is False
    assert (
        db_session.query(CompletedWorkORM)
        .filter(CompletedWorkORM.door_id == door.id)
        .count()
        == 0
    )
    queue_row = db_session.get(SyncQueueItemORM, uuid.UUID(item["id"]))
    assert queue_row is not None
    assert queue_row.user_id == user.id
    assert queue_row.status == "CONFLICT"
    assert queue_row.conflict_code == "CONFLICT_INVALID_TRANSITION"


def test_sync_queue_batch_rejects_locked_door_even_with_current_version(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, user = installer_sync_batch_client
    project = _make_project(company_id=company_id, name="Batch Locked Door")
    door_type = make_door_type(name="Batch Locked Door Type")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=installer_id,
        status=DoorStatus.IN_PROGRESS,
        version=2,
    )
    door.is_locked = True
    db_session.add(door)
    db_session.commit()

    item = _batch_item(
        project_id=project.id,
        door_id=door.id,
        status="INSTALLED",
        base_version=2,
    )
    resp = client.post(
        "/api/v1/installer/sync-queue/batch",
        json={
            "device_id": "sync-batch-device",
            "items": [item],
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "CONFLICT"
    assert result["conflict_code"] == "CONFLICT_INVALID_TRANSITION"
    assert result["new_version"] is None

    db_session.refresh(door)
    assert door.status == DoorStatus.IN_PROGRESS
    assert door.version == 2
    assert door.is_locked is True
    assert (
        db_session.query(CompletedWorkORM)
        .filter(CompletedWorkORM.company_id == company_id)
        .filter(CompletedWorkORM.door_id == door.id)
        .count()
        == 0
    )

    queue_row = (
        db_session.query(SyncQueueItemORM)
        .filter(
            SyncQueueItemORM.company_id == company_id,
            SyncQueueItemORM.user_id == user.id,
            SyncQueueItemORM.id == uuid.UUID(item["id"]),
        )
        .one()
    )
    assert queue_row.status == "CONFLICT"
    assert queue_row.conflict_code == "CONFLICT_INVALID_TRANSITION"


def test_sync_queue_batch_returns_conflict_assignment_changed_for_reassigned_door(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
    make_installer,
):
    client, installer_id, user = installer_sync_batch_client
    other_installer = make_installer(full_name="Other Sync", phone="+972500001111")
    project = _make_project(company_id=company_id, name="Batch Assignment")
    door_type = make_door_type(name="Batch Assignment Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=other_installer.id,
        status=DoorStatus.NOT_INSTALLED,
        version=0,
    )
    db_session.add(door)
    db_session.commit()

    item = _batch_item(
        project_id=project.id,
        door_id=door.id,
        status="IN_PROGRESS",
        base_version=0,
    )
    resp = client.post(
        "/api/v1/installer/sync-queue/batch",
        json={
            "device_id": "sync-batch-device",
            "items": [item],
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "CONFLICT"
    assert result["conflict_code"] == "CONFLICT_ASSIGNMENT_CHANGED"

    queue_row = (
        db_session.query(SyncQueueItemORM)
        .filter(
            SyncQueueItemORM.company_id == company_id,
            SyncQueueItemORM.user_id == user.id,
            SyncQueueItemORM.id == uuid.UUID(item["id"]),
        )
        .one()
    )
    assert queue_row.status == "CONFLICT"
    assert queue_row.conflict_code == "CONFLICT_ASSIGNMENT_CHANGED"


def test_sync_queue_batch_reassigned_installed_event_does_not_create_earnings(
    installer_sync_batch_client,
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
    make_installer,
):
    client, installer_id, user = installer_sync_batch_client
    other_installer = make_installer(
        full_name="Other Install Earnings Sync",
        phone="+972500001112",
    )
    project = _make_project(company_id=company_id, name="Batch Reassigned Install")
    door_type = make_door_type(name="Batch Reassigned Install Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=installer_id,
        status=DoorStatus.IN_PROGRESS,
        version=1,
    )
    door.installer_rate_snapshot = Decimal("90.00")
    db_session.add(door)
    db_session.commit()

    reassign_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/doors/bulk-assign-installer",
        json={
            "door_ids": [str(door.id)],
            "installer_id": str(other_installer.id),
        },
    )
    assert reassign_resp.status_code == 200, reassign_resp.text
    assert reassign_resp.json()["assigned"] == 1

    item = _batch_item(
        project_id=project.id,
        door_id=door.id,
        status="INSTALLED",
        base_version=1,
    )
    resp = client.post(
        "/api/v1/installer/sync-queue/batch",
        json={
            "device_id": "sync-batch-device-reassigned-install",
            "items": [item],
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "CONFLICT"
    assert result["conflict_code"] == "CONFLICT_ASSIGNMENT_CHANGED"
    assert result["new_version"] is None

    db_session.refresh(door)
    assert door.installer_id == other_installer.id
    assert door.status == DoorStatus.IN_PROGRESS
    assert door.version == 1
    assert door.is_locked is False
    assert (
        db_session.query(CompletedWorkORM)
        .filter(CompletedWorkORM.company_id == company_id)
        .filter(CompletedWorkORM.door_id == door.id)
        .count()
        == 0
    )

    queue_row = (
        db_session.query(SyncQueueItemORM)
        .filter(
            SyncQueueItemORM.company_id == company_id,
            SyncQueueItemORM.user_id == user.id,
            SyncQueueItemORM.id == uuid.UUID(item["id"]),
        )
        .one()
    )
    assert queue_row.status == "CONFLICT"
    assert queue_row.conflict_code == "CONFLICT_ASSIGNMENT_CHANGED"


def test_sync_queue_batch_marks_item_auth_required_when_apply_hits_auth_boundary(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
    monkeypatch,
):
    client, installer_id, user = installer_sync_batch_client
    project = _make_project(company_id=company_id, name="Batch Auth Required")
    door_type = make_door_type(name="Batch Auth Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=installer_id,
        status=DoorStatus.NOT_INSTALLED,
        version=0,
    )
    db_session.add(door)
    db_session.commit()

    def _raise_auth(*args, **kwargs):
        raise Unauthorized("Re-authentication required before applying queued item")

    monkeypatch.setattr(InstallerSyncService, "_apply_batch_item", staticmethod(_raise_auth))

    item = _batch_item(
        project_id=project.id,
        door_id=door.id,
        status="IN_PROGRESS",
        base_version=0,
    )
    resp = client.post(
        "/api/v1/installer/sync-queue/batch",
        json={
            "device_id": "sync-batch-device",
            "items": [item],
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "AUTH_REQUIRED"
    assert result["conflict_code"] is None

    queue_row = (
        db_session.query(SyncQueueItemORM)
        .filter(
            SyncQueueItemORM.company_id == company_id,
            SyncQueueItemORM.user_id == user.id,
            SyncQueueItemORM.id == uuid.UUID(item["id"]),
        )
        .one()
    )
    assert queue_row.status == "AUTH_REQUIRED"
    assert queue_row.conflict_code is None
    assert queue_row.synced_at is None


def test_sync_queue_batch_rolls_back_partial_changes_on_conflict(
    installer_sync_batch_client,
    db_session,
    company_id,
    make_door_type,
    monkeypatch,
):
    client, installer_id, user = installer_sync_batch_client
    project = _make_project(company_id=company_id, name="Batch Savepoint")
    door_type = make_door_type(name="Batch Savepoint Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=installer_id,
        status=DoorStatus.NOT_INSTALLED,
        version=0,
    )
    db_session.add(door)
    db_session.commit()

    def _mutate_then_fail(uow, **kwargs):
        target = uow.doors.get(company_id=company_id, door_id=door.id)
        target.comment = "must be rolled back"
        uow.session.flush()
        raise ValidationError("forced offline conflict")

    monkeypatch.setattr(
        InstallerSyncService,
        "_apply_batch_item",
        staticmethod(_mutate_then_fail),
    )

    item = _batch_item(
        project_id=project.id,
        door_id=door.id,
        status="IN_PROGRESS",
        base_version=0,
    )
    response = client.post(
        "/api/v1/installer/sync-queue/batch",
        json={"device_id": "sync-savepoint-device", "items": [item]},
    )
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "CONFLICT"
    assert result["conflict_code"] == "CONFLICT_INVALID_TRANSITION"

    db_session.expire_all()
    persisted_door = db_session.query(DoorORM).filter(DoorORM.id == door.id).one()
    assert persisted_door.comment is None
    queue_row = (
        db_session.query(SyncQueueItemORM)
        .filter(
            SyncQueueItemORM.company_id == company_id,
            SyncQueueItemORM.user_id == user.id,
            SyncQueueItemORM.id == uuid.UUID(item["id"]),
        )
        .one()
    )
    assert queue_row.status == "CONFLICT"
    assert queue_row.conflict_code == "CONFLICT_INVALID_TRANSITION"
