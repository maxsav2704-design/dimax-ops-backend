from __future__ import annotations

from datetime import datetime, timezone

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.sync.domain.enums import SyncChangeType
from app.modules.sync.infrastructure.models import SyncChangeLogORM


def test_installer_sync_reset_snapshot_includes_projects(
    client_installer,
    db_session,
    company_id,
    installer_user,
    make_door_type,
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
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(door)
    db_session.flush()
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
    assert body["snapshot"]["projects"][0]["name"] == "Snapshot Project"
    assert body["snapshot"]["projects"][0]["address"] == "1 Snapshot Street"
    assert body["snapshot"]["projects"][0]["status"] == "OK"
    assert body["snapshot"]["projects"][0]["waze_url"] is not None
    assert len(body["snapshot"]["doors"]) == 1
    assert body["snapshot"]["doors"][0]["project_id"] == str(project.id)
