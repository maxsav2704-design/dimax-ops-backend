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
        code=f"PRJ-{uuid.uuid4().hex[:6].upper()}",
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


def _assert_exact_keys(payload: dict, expected: set[str]) -> None:
    assert set(payload.keys()) == expected


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
    pagination = resp.json()["pagination"]
    item_ids = [row["id"] for row in items]

    assert str(project_a.id) in item_ids
    assert str(project_b.id) in item_ids
    assert str(project_foreign.id) not in item_ids
    assert item_ids.count(str(project_a.id)) == 1
    row_a = next(x for x in items if x["id"] == str(project_a.id))
    _assert_exact_keys(row_a, {"id", "name", "address", "status", "waze_url"})
    assert row_a["waze_url"] is not None
    assert "navigate=yes" in row_a["waze_url"]
    assert pagination["page"] == 1
    assert pagination["per_page"] == 25
    assert pagination["total"] == 2
    assert pagination["total_pages"] == 1


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
    project.address_street = "Harbor"
    project.address_building = "11"
    project.address_city = "Ashdod"
    project.address_entrance = "A"
    project.address_lat = Decimal("31.801")
    project.address_lng = Decimal("34.643")
    project.address_waze_url = "https://www.waze.com/ul?q=Manual+Installer+Link"
    project.developer_company = "Builder Ltd"
    project.contact_name = "Yael Cohen"
    project.contact_phone = "+972501234567"
    project.developer_phone_alt = "+972502224466"
    project.developer_whatsapp = "+972509876543"
    project.developer_notes = "Gate code 7788"
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

    resp = client.get(
        f"/api/v1/installer/projects/{project.id}",
        headers={"Accept-Language": "he"},
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    _assert_exact_keys(
        body,
        {
            "id",
            "name",
            "address",
            "address_details",
            "waze_url",
            "whatsapp_url",
            "call_url",
            "developer",
            "contact_name",
            "contact_phone",
            "developer_phone_alt",
            "developer_whatsapp",
            "developer_company",
            "developer_notes",
            "status",
            "doors",
            "issues_open",
            "door_types_catalog",
            "reasons_catalog",
            "addons",
            "server_time",
        },
    )
    assert body["id"] == str(project.id)
    assert body["name"] == "Installer Details Project"
    assert body["address_details"] == {
        "street": "Harbor",
        "building": "11",
        "city": "Ashdod",
        "entrance": "A",
        "lat": "31.801",
        "lng": "34.643",
        "waze_url": "https://www.waze.com/ul?q=Manual+Installer+Link",
        "waze_deep_link": "https://waze.com/ul?ll=31.801,34.643&navigate=yes",
    }
    assert body["waze_url"] is not None
    assert body["waze_url"] == "https://waze.com/ul?ll=31.801,34.643&navigate=yes"
    assert body["whatsapp_url"] is not None
    assert "wa.me/972509876543" in body["whatsapp_url"]
    assert "%D7%A9%D7%9C%D7%95%D7%9D%2C+%D7%91%D7%A7%D7%A9%D7%A8+%D7%9C%D7%A4%D7%A8%D7%95%D7%99%D7%A7%D7%98+Installer+Details+Project" in body["whatsapp_url"]
    assert body["call_url"] == "tel:+972501234567"
    assert body["contact_name"] == "Yael Cohen"
    assert body["contact_phone"] == "+972501234567"
    assert body["developer_phone_alt"] == "+972502224466"
    assert body["developer_whatsapp"] == "+972509876543"
    assert body["developer"] == {
        "name": "Builder Ltd",
        "contact_name": "Yael Cohen",
        "phone": "+972501234567",
        "phone_alt": "+972502224466",
        "whatsapp": "+972509876543",
        "notes": "Gate code 7788",
        "whatsapp_deep_link": body["whatsapp_url"],
        "call_deep_link": "tel:+972501234567",
    }
    assert body["developer_company"] == "Builder Ltd"
    assert body["developer_notes"] == "Gate code 7788"
    assert "contact_email" not in body

    doors = body["doors"]
    assert [d["unit_label"] for d in doors] == ["A-01", "A-02"]
    _assert_exact_keys(
        doors[0],
        {
            "id",
            "unit_label",
            "door_type_id",
            "order_number",
            "house_number",
            "floor_label",
            "apartment_number",
            "location_code",
            "door_marking",
            "status",
            "reason_id",
            "comment",
            "is_locked",
        },
    )

    issues = body["issues_open"]
    assert len(issues) == 1
    _assert_exact_keys(issues[0], {"id", "door_id", "status", "title", "details"})
    assert issues[0]["id"] == str(issue_open.id)

    door_types_catalog = body["door_types_catalog"]
    _assert_exact_keys(door_types_catalog[0], {"id", "code", "name"})
    assert any(x["id"] == str(door_type.id) for x in door_types_catalog)
    reasons_catalog = body["reasons_catalog"]
    assert isinstance(reasons_catalog, list)

    addons = body["addons"]
    _assert_exact_keys(addons, {"types", "plan", "facts"})
    assert len(addons["types"]) == 1
    _assert_exact_keys(addons["types"][0], {"id", "name", "unit"})
    assert addons["types"][0]["id"] == str(addon_type.id)
    assert len(addons["plan"]) == 1
    _assert_exact_keys(
        addons["plan"][0],
        {"addon_type_id", "qty_planned"},
    )
    assert addons["plan"][0]["addon_type_id"] == str(addon_type.id)
    assert len(addons["facts"]) == 1
    _assert_exact_keys(
        addons["facts"][0],
        {"id", "addon_type_id", "qty_done", "done_at", "comment", "source"},
    )
    assert addons["facts"][0]["id"] == str(addon_fact_my.id)


def test_installer_project_response_has_no_financial_fields(
    client_installer_projects,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id = client_installer_projects

    door_type = make_door_type(name="Leakage Guard Door")
    project = _make_project(
        company_id=company_id,
        name="Leakage Guard Project",
        address="Leakage address",
    )
    db_session.add(project)
    db_session.flush()

    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="L-01",
        installer_id=installer_id,
    )
    db_session.add(door)

    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Seal leakage guard",
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
        client_price=Decimal("50.00"),
        installer_price=Decimal("20.00"),
    )
    db_session.add(addon_plan)
    db_session.commit()

    resp = client.get(f"/api/v1/installer/projects/{project.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    for row in body.get("doors", []):
        assert "our_price" not in row
        assert "client_price" not in row
        assert "installer_price" not in row
        assert "surcharge_pct" not in row
        assert "margin" not in row
        assert "rate_snapshot" not in row

    for row in body.get("addons", {}).get("plan", []):
        assert "client_price" not in row
        assert "installer_price" not in row
        assert "surcharge_pct" not in row
        assert "margin" not in row


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
