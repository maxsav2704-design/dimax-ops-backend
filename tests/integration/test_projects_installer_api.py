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
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.issues.domain.enums import IssueStatus
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


@pytest.fixture()
def client_installer_projects(installer_user: CurrentUser, db_session):
    installer = InstallerORM(
        company_id=installer_user.company_id,
        full_name="Installer Projects",
        phone=f"+1777{uuid.uuid4().hex[:8]}",
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


def _make_project(*, company_id: uuid.UUID, name: str, address: str) -> ProjectORM:
    return ProjectORM(
        company_id=company_id,
        name=name,
        address=address,
        status=ProjectStatus.OK,
    )


def _make_door(
    *,
    company_id: uuid.UUID,
    project_id: uuid.UUID,
    door_type_id: uuid.UUID,
    unit_label: str,
    installer_id: uuid.UUID | None,
) -> DoorORM:
    return DoorORM(
        company_id=company_id,
        project_id=project_id,
        door_type_id=door_type_id,
        unit_label=unit_label,
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer_id,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )


def test_installer_projects_list_shows_only_assigned_projects(
    client_installer_projects,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id = client_installer_projects
    other_installer = InstallerORM(
        company_id=company_id,
        full_name="Other Installer",
        phone=f"+1888{uuid.uuid4().hex[:8]}",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=None,
    )
    db_session.add(other_installer)

    door_type = make_door_type(name="Project List Door")

    project_a = _make_project(
        company_id=company_id,
        name="Installer Project A",
        address="Address A",
    )
    project_b = _make_project(
        company_id=company_id,
        name="Installer Project B",
        address="Address B",
    )
    project_foreign = _make_project(
        company_id=company_id,
        name="Installer Project Foreign",
        address="Address Foreign",
    )
    db_session.add_all([project_a, project_b, project_foreign])
    db_session.flush()

    db_session.add_all(
        [
            _make_door(
                company_id=company_id,
                project_id=project_a.id,
                door_type_id=door_type.id,
                unit_label="A-1",
                installer_id=installer_id,
            ),
            _make_door(
                company_id=company_id,
                project_id=project_a.id,
                door_type_id=door_type.id,
                unit_label="A-2",
                installer_id=installer_id,
            ),
            _make_door(
                company_id=company_id,
                project_id=project_b.id,
                door_type_id=door_type.id,
                unit_label="B-1",
                installer_id=installer_id,
            ),
            _make_door(
                company_id=company_id,
                project_id=project_foreign.id,
                door_type_id=door_type.id,
                unit_label="F-1",
                installer_id=other_installer.id,
            ),
        ]
    )
    db_session.commit()

    resp = client.get("/api/v1/installer/projects")
    assert resp.status_code == 200, resp.text

    items = resp.json()["items"]
    item_ids = [row["id"] for row in items]

    assert str(project_a.id) in item_ids
    assert str(project_b.id) in item_ids
    assert str(project_foreign.id) not in item_ids
    assert item_ids.count(str(project_a.id)) == 1
    row_a = next(x for x in items if x["id"] == str(project_a.id))
    assert row_a["waze_url"] is not None
    assert "navigate=yes" in row_a["waze_url"]


def test_installer_project_details_returns_scoped_data(
    client_installer_projects,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id = client_installer_projects

    other_installer = InstallerORM(
        company_id=company_id,
        full_name="Other Installer Details",
        phone=f"+1999{uuid.uuid4().hex[:8]}",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=None,
    )
    db_session.add(other_installer)

    door_type = make_door_type(name="Project Details Door")
    project = _make_project(
        company_id=company_id,
        name="Installer Details Project",
        address="Details address",
    )
    db_session.add(project)
    db_session.flush()

    my_door_1 = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="A-02",
        installer_id=installer_id,
    )
    my_door_2 = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="A-01",
        installer_id=installer_id,
    )
    foreign_door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="B-01",
        installer_id=other_installer.id,
    )
    db_session.add_all([my_door_1, my_door_2, foreign_door])
    db_session.flush()

    issue_open = IssueORM(
        company_id=company_id,
        door_id=my_door_1.id,
        status=IssueStatus.OPEN,
        title="Open issue",
        details="Open details",
    )
    issue_closed = IssueORM(
        company_id=company_id,
        door_id=my_door_2.id,
        status=IssueStatus.CLOSED,
        title="Closed issue",
        details="Closed details",
    )
    db_session.add_all([issue_open, issue_closed])

    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Seal",
        unit="pcs",
        default_client_price=Decimal("10.00"),
        default_installer_price=Decimal("5.00"),
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
        client_price=Decimal("20.00"),
        installer_price=Decimal("8.00"),
    )
    addon_fact_my = ProjectAddonFactORM(
        company_id=company_id,
        project_id=project.id,
        addon_type_id=addon_type.id,
        installer_id=installer_id,
        qty_done=Decimal("1.00"),
        done_at=datetime.now(timezone.utc),
        comment="done by me",
        source=AddonFactSource.ONLINE,
        client_event_id=None,
    )
    addon_fact_other = ProjectAddonFactORM(
        company_id=company_id,
        project_id=project.id,
        addon_type_id=addon_type.id,
        installer_id=other_installer.id,
        qty_done=Decimal("3.00"),
        done_at=datetime.now(timezone.utc),
        comment="done by other",
        source=AddonFactSource.ONLINE,
        client_event_id=None,
    )

    db_session.add_all([addon_plan, addon_fact_my, addon_fact_other])
    db_session.commit()

    resp = client.get(f"/api/v1/installer/projects/{project.id}")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["id"] == str(project.id)
    assert body["name"] == "Installer Details Project"
    assert body["waze_url"] is not None
    assert "navigate=yes" in body["waze_url"]

    doors = body["doors"]
    assert [d["unit_label"] for d in doors] == ["A-01", "A-02"]

    issues = body["issues_open"]
    assert len(issues) == 1
    assert issues[0]["id"] == str(issue_open.id)

    door_types_catalog = body["door_types_catalog"]
    assert any(x["id"] == str(door_type.id) for x in door_types_catalog)
    reasons_catalog = body["reasons_catalog"]
    assert isinstance(reasons_catalog, list)

    addons = body["addons"]
    assert len(addons["types"]) == 1
    assert addons["types"][0]["id"] == str(addon_type.id)
    assert len(addons["plan"]) == 1
    assert addons["plan"][0]["addon_type_id"] == str(addon_type.id)
    assert len(addons["facts"]) == 1
    assert addons["facts"][0]["id"] == str(addon_fact_my.id)


def test_installer_project_details_forbidden_if_not_assigned(
    client_installer_projects,
    db_session,
    company_id,
    make_door_type,
):
    client, _installer_id = client_installer_projects

    project = _make_project(
        company_id=company_id,
        name="Not Assigned Project",
        address="No access address",
    )
    db_session.add(project)

    door_type = make_door_type(name="Forbidden Door")
    other_installer = InstallerORM(
        company_id=company_id,
        full_name="Other Installer Forbidden",
        phone=f"+1666{uuid.uuid4().hex[:8]}",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=None,
    )
    db_session.add(other_installer)
    db_session.flush()

    db_session.add(
        _make_door(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            unit_label="X-1",
            installer_id=other_installer.id,
        )
    )
    db_session.commit()

    resp = client.get(f"/api/v1/installer/projects/{project.id}")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_installer_project_details_returns_404_for_missing_project(
    client_installer_projects,
):
    client, _installer_id = client_installer_projects

    resp = client.get(f"/api/v1/installer/projects/{uuid.uuid4()}")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_installer_project_details_validation_returns_422_for_bad_uuid(
    client_installer_projects,
):
    client, _installer_id = client_installer_projects

    resp = client.get("/api/v1/installer/projects/not-a-uuid")
    assert resp.status_code == 422, resp.text
