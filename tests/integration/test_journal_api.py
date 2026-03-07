from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.journal.domain.enums import JournalStatus
from app.modules.journal.infrastructure.models import JournalORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


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


def _create_door(
    db_session,
    *,
    company_id: uuid.UUID,
    project_id: uuid.UUID,
    door_type_id: uuid.UUID,
    unit_label: str,
    status: DoorStatus,
) -> DoorORM:
    installed_at = datetime.now(timezone.utc) if status == DoorStatus.INSTALLED else None
    row = DoorORM(
        company_id=company_id,
        project_id=project_id,
        door_type_id=door_type_id,
        unit_label=unit_label,
        our_price=Decimal("100.00"),
        status=status,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=installed_at,
        is_locked=False,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_journal_admin_public_sign_flow(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name="Journal Flow Project",
    )
    door_type = make_door_type(name="Journal Flow Door Type")

    _create_door(
        db_session,
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="A-01",
        status=DoorStatus.INSTALLED,
    )
    _create_door(
        db_session,
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="A-02",
        status=DoorStatus.NOT_INSTALLED,
    )

    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/journals",
        json={
            "project_id": str(project.id),
            "title": "Acceptance Journal",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    journal_id = create_resp.json()["id"]

    list_resp = client_admin_real_uow.get("/api/v1/admin/journals")
    assert list_resp.status_code == 200, list_resp.text
    listed = {item["id"]: item for item in list_resp.json()["items"]}
    assert journal_id in listed
    assert listed[journal_id]["status"] == "DRAFT"

    get_resp = client_admin_real_uow.get(f"/api/v1/admin/journals/{journal_id}")
    assert get_resp.status_code == 200, get_resp.text
    details = get_resp.json()
    assert details["title"] == "Acceptance Journal"
    assert details["status"] == "DRAFT"
    assert details["snapshot_version"] >= 2

    patch_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/journals/{journal_id}",
        json={"notes": "ready to sign", "lock_header": True},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["ok"] is True

    patch_locked_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/journals/{journal_id}",
        json={"title": "Should Not Apply"},
    )
    assert patch_locked_resp.status_code == 200, patch_locked_resp.text

    get_after_patch_resp = client_admin_real_uow.get(
        f"/api/v1/admin/journals/{journal_id}"
    )
    assert get_after_patch_resp.status_code == 200, get_after_patch_resp.text
    after_patch = get_after_patch_resp.json()
    assert after_patch["title"] == "Acceptance Journal"
    assert after_patch["notes"] == "ready to sign"
    assert after_patch["lock_header"] is True

    mark_ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert mark_ready_resp.status_code == 200, mark_ready_resp.text
    mark_ready_body = mark_ready_resp.json()
    token = mark_ready_body["public_token"]
    assert mark_ready_body["public_url"].endswith(token)

    public_get_resp = client_admin_real_uow.get(f"/api/v1/public/journals/{token}")
    assert public_get_resp.status_code == 200, public_get_resp.text
    public_body = public_get_resp.json()
    assert public_body["journal"]["status"] == "ACTIVE"
    assert len(public_body["items"]) == 1
    assert public_body["items"][0]["unit_label"] == "A-01"

    sign_resp = client_admin_real_uow.post(
        f"/api/v1/public/journals/{token}/sign",
        json={
            "signer_name": "Client Name",
            "signature_payload": {"strokes": [1, 2, 3]},
        },
    )
    assert sign_resp.status_code == 200, sign_resp.text
    assert sign_resp.json()["ok"] is True

    after_sign_resp = client_admin_real_uow.get(
        f"/api/v1/admin/journals/{journal_id}"
    )
    assert after_sign_resp.status_code == 200, after_sign_resp.text
    after_sign = after_sign_resp.json()
    assert after_sign["status"] == "ARCHIVED"
    assert after_sign["signer_name"] == "Client Name"
    assert after_sign["signed_at"] is not None

    second_sign_resp = client_admin_real_uow.post(
        f"/api/v1/public/journals/{token}/sign",
        json={
            "signer_name": "Client Name",
            "signature_payload": {"strokes": [4, 5]},
        },
    )
    assert second_sign_resp.status_code == 403, second_sign_resp.text
    assert second_sign_resp.json()["error"]["code"] == "FORBIDDEN"


def test_journal_admin_endpoints_forbidden_for_installer_role(client_installer):
    list_resp = client_installer.get("/api/v1/admin/journals")
    assert list_resp.status_code == 403, list_resp.text
    assert list_resp.json()["error"]["code"] == "FORBIDDEN"

    create_resp = client_installer.post(
        "/api/v1/admin/journals",
        json={"project_id": str(uuid.uuid4())},
    )
    assert create_resp.status_code == 403, create_resp.text
    assert create_resp.json()["error"]["code"] == "FORBIDDEN"


def test_journal_validation_returns_422(client_admin_real_uow):
    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/journals",
        json={},
    )
    assert create_resp.status_code == 422, create_resp.text

    list_resp = client_admin_real_uow.get("/api/v1/admin/journals?limit=0")
    assert list_resp.status_code == 422, list_resp.text

    sign_resp = client_admin_real_uow.post(
        "/api/v1/public/journals/some-token/sign",
        json={
            "signer_name": "A",
            "signature_payload": {"x": 1},
        },
    )
    assert sign_resp.status_code == 422, sign_resp.text


def test_journal_public_link_expired_returns_not_found(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name="Journal Expire Project",
    )
    door_type = make_door_type(name="Journal Expire Door Type")
    _create_door(
        db_session,
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="E-01",
        status=DoorStatus.INSTALLED,
    )

    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/journals",
        json={"project_id": str(project.id), "title": "Expiring Journal"},
    )
    assert create_resp.status_code == 200, create_resp.text
    journal_id = create_resp.json()["id"]

    ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert ready_resp.status_code == 200, ready_resp.text
    token = ready_resp.json()["public_token"]

    journal_row = (
        db_session.query(JournalORM)
        .filter(JournalORM.id == uuid.UUID(journal_id))
        .one()
    )
    journal_row.public_token_expires_at = datetime.now(timezone.utc) - timedelta(
        minutes=1
    )
    db_session.add(journal_row)
    db_session.commit()

    public_get_resp = client_admin_real_uow.get(f"/api/v1/public/journals/{token}")
    assert public_get_resp.status_code == 404, public_get_resp.text
    assert public_get_resp.json()["error"]["code"] == "NOT_FOUND"

    sign_resp = client_admin_real_uow.post(
        f"/api/v1/public/journals/{token}/sign",
        json={
            "signer_name": "Client Name",
            "signature_payload": {"strokes": [1]},
        },
    )
    assert sign_resp.status_code == 404, sign_resp.text
    assert sign_resp.json()["error"]["code"] == "NOT_FOUND"


def test_journal_multi_tenant_isolation_for_admin(
    client_admin_real_uow,
    db_session,
):
    foreign_company_id = uuid.uuid4()
    foreign_project_id = uuid.uuid4()
    foreign_journal_id = uuid.uuid4()

    db_session.add(
        CompanyORM(
            id=foreign_company_id,
            name=f"Foreign {foreign_company_id}",
            is_active=True,
        )
    )
    db_session.add(
        ProjectORM(
            id=foreign_project_id,
            company_id=foreign_company_id,
            name="Foreign Journal Project",
            address="Foreign Address",
            status=ProjectStatus.OK,
        )
    )
    db_session.commit()
    db_session.add(
        JournalORM(
            id=foreign_journal_id,
            company_id=foreign_company_id,
            project_id=foreign_project_id,
            status=JournalStatus.DRAFT,
            title="Foreign Journal",
            notes=None,
            public_token=None,
            public_token_expires_at=None,
            lock_header=False,
            lock_table=False,
            lock_footer=False,
            signed_at=None,
            signer_name=None,
            snapshot_version=1,
        )
    )
    db_session.commit()

    try:
        list_resp = client_admin_real_uow.get("/api/v1/admin/journals")
        assert list_resp.status_code == 200, list_resp.text
        listed_ids = {item["id"] for item in list_resp.json()["items"]}
        assert str(foreign_journal_id) not in listed_ids

        get_resp = client_admin_real_uow.get(
            f"/api/v1/admin/journals/{foreign_journal_id}"
        )
        assert get_resp.status_code == 404, get_resp.text
        assert get_resp.json()["error"]["code"] == "NOT_FOUND"
    finally:
        db_session.rollback()
        db_session.execute(
            text("DELETE FROM journals WHERE company_id = :cid"),
            {"cid": foreign_company_id},
        )
        db_session.execute(
            text("DELETE FROM projects WHERE company_id = :cid"),
            {"cid": foreign_company_id},
        )
        db_session.execute(
            text("DELETE FROM companies WHERE id = :cid"),
            {"cid": foreign_company_id},
        )
        db_session.commit()
