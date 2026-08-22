from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from app.modules.addons.domain.enums import AddonFactSource
from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.identity.infrastructure.models import CompanyORM, UserORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.journal.domain.enums import JournalStatus
from app.modules.journal.infrastructure.models import (
    JournalORM,
    JournalSignatureORM,
)
from app.modules.journal.infrastructure.repositories import JournalRepository
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


def _create_project(db_session, *, company_id: uuid.UUID, name: str) -> ProjectORM:
    row = ProjectORM(
        company_id=company_id,
        name=name,
        address=f"{name} address",
        contact_email=f"acceptance-{uuid.uuid4().hex[:8]}@example.com",
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
    installer_id: uuid.UUID | None = None,
) -> DoorORM:
    installed_at = datetime.now(timezone.utc) if status == DoorStatus.INSTALLED else None
    row = DoorORM(
        company_id=company_id,
        project_id=project_id,
        door_type_id=door_type_id,
        unit_label=unit_label,
        our_price=Decimal("100.00"),
        status=status,
        installer_id=installer_id,
        reason_id=None,
        comment=None,
        installed_at=installed_at,
        is_locked=False,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_installer_journal_is_scoped_and_signed_pdf_is_queued_for_delivery(
    client_installer,
    installer_user,
    admin_user,
    db_session,
    company_id,
    make_door_type,
):
    installer = InstallerORM(
        company_id=company_id,
        full_name="Journal Installer",
        phone=f"+97250{uuid.uuid4().hex[:7]}",
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
        full_name="Other Journal Installer",
        phone=f"+97251{uuid.uuid4().hex[:7]}",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=None,
    )
    db_session.add_all([installer, other_installer])
    db_session.commit()
    db_session.refresh(installer)
    db_session.refresh(other_installer)

    project = _create_project(
        db_session,
        company_id=company_id,
        name="Installer Journal Project",
    )
    project.developer_company = "Builder Acceptance Ltd"
    project.contact_email = "acceptance@builder.example"
    foreign_project = _create_project(
        db_session,
        company_id=company_id,
        name="Foreign Installer Journal Project",
    )
    door_type = make_door_type(name="Installer Journal Door")
    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Frame adjustment",
        unit="pcs",
        default_client_price=Decimal("20.00"),
        default_installer_price=Decimal("10.00"),
        is_active=True,
    )
    db_session.add(addon_type)
    db_session.commit()
    db_session.refresh(addon_type)

    _create_door(
        db_session,
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="OWN-01",
        status=DoorStatus.INSTALLED,
        installer_id=installer.id,
    )
    _create_door(
        db_session,
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="OTHER-01",
        status=DoorStatus.INSTALLED,
        installer_id=other_installer.id,
    )
    _create_door(
        db_session,
        company_id=company_id,
        project_id=foreign_project.id,
        door_type_id=door_type.id,
        unit_label="FOREIGN-01",
        status=DoorStatus.INSTALLED,
        installer_id=other_installer.id,
    )
    db_session.add_all(
        [
            ProjectAddonFactORM(
                company_id=company_id,
                project_id=project.id,
                addon_type_id=addon_type.id,
                installer_id=installer.id,
                qty_done=Decimal("2.00"),
                done_at=datetime.now(timezone.utc),
                comment="Own completed addon",
                source=AddonFactSource.ONLINE,
                client_event_id=f"journal-own-{uuid.uuid4().hex}",
            ),
            ProjectAddonFactORM(
                company_id=company_id,
                project_id=project.id,
                addon_type_id=addon_type.id,
                installer_id=other_installer.id,
                qty_done=Decimal("3.00"),
                done_at=datetime.now(timezone.utc),
                comment="Other installer addon",
                source=AddonFactSource.ONLINE,
                client_event_id=f"journal-other-{uuid.uuid4().hex}",
            ),
        ]
    )
    db_session.commit()

    denied = client_installer.post(
        "/api/v1/installer/journals/prepare",
        json={"project_id": str(foreign_project.id)},
    )
    assert denied.status_code == 403, denied.text

    prepared = client_installer.post(
        "/api/v1/installer/journals/prepare",
        json={"project_id": str(project.id)},
    )
    assert prepared.status_code == 200, prepared.text
    prepared_body = prepared.json()
    assert prepared_body["completed_doors"] == 1
    assert prepared_body["completed_addons"] == 1
    assert [row["unit_label"] for row in prepared_body["doors"]] == ["OWN-01"]
    assert [row["comment"] for row in prepared_body["addon_items"]] == [
        "Own completed addon"
    ]

    listed = client_installer.get("/api/v1/installer/journals")
    assert listed.status_code == 200, listed.text
    assert [row["project_id"] for row in listed.json()["items"]] == [
        str(project.id)
    ]

    journal_id = prepared_body["id"]
    ready = client_installer.post(
        f"/api/v1/installer/journals/{journal_id}/mark-ready"
    )
    assert ready.status_code == 200, ready.text
    signing_url = ready.json()["signing_url"]
    token = signing_url.rsplit("/", 1)[-1]

    public_document = client_installer.get(f"/api/v1/public/journals/{token}")
    assert public_document.status_code == 200, public_document.text
    assert [row["unit_label"] for row in public_document.json()["items"]] == [
        "OWN-01"
    ]
    assert len(public_document.json()["addon_items"]) == 1

    signed = client_installer.post(
        f"/api/v1/public/journals/{token}/sign",
        json={
            "signer_name": "Developer Representative",
            "signature_payload": {
                "version": 1,
                "viewport": {"width": 320, "height": 120},
                "strokes": [
                    [{"x": 20, "y": 70}, {"x": 140, "y": 35}]
                ],
            },
        },
    )
    assert signed.status_code == 200, signed.text
    assert signed.json() == {
        "ok": True,
        "pdf_ready": True,
        "email_queued": True,
    }

    db_session.expire_all()
    admin_email = (
        db_session.query(UserORM.email).filter(UserORM.id == admin_user.id).scalar()
    )
    message = (
        db_session.query(OutboxMessageORM)
        .filter(
            OutboxMessageORM.company_id == company_id,
            OutboxMessageORM.correlation_id == uuid.UUID(journal_id),
        )
        .one()
    )
    assert message.payload["to_email"] == "acceptance@builder.example"
    assert admin_email in message.payload["cc_emails"]
    assert message.payload["delivery_reason"] == "SIGNED_JOURNAL"
    assert message.payload["attachment_name"].endswith(".pdf")


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


def test_public_journal_can_only_be_signed_once_concurrently(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
    monkeypatch,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Concurrent Journal {uuid.uuid4().hex[:8]}",
    )
    door_type = make_door_type(name="Concurrent Journal Door")
    _create_door(
        db_session,
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="CONCURRENT-01",
        status=DoorStatus.INSTALLED,
    )
    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/journals",
        json={"project_id": str(project.id), "title": "Concurrent acceptance"},
    )
    assert create_resp.status_code == 200, create_resp.text
    journal_id = create_resp.json()["id"]
    ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert ready_resp.status_code == 200, ready_resp.text
    token = ready_resp.json()["public_token"]

    original_get_by_token = JournalRepository.get_by_token

    def slow_get_by_token(self, *, token, for_update=False):
        journal = original_get_by_token(
            self,
            token=token,
            for_update=for_update,
        )
        if for_update:
            time.sleep(0.2)
        return journal

    monkeypatch.setattr(JournalRepository, "get_by_token", slow_get_by_token)

    start = threading.Barrier(2)
    app = create_app()
    with TestClient(app) as first_client, TestClient(app) as second_client:
        def sign_once(client, signer_name):
            start.wait(timeout=10)
            return client.post(
                f"/api/v1/public/journals/{token}/sign",
                json={
                    "signer_name": signer_name,
                    "signature_payload": {"strokes": [signer_name]},
                },
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(sign_once, first_client, "First Client")
            second = executor.submit(sign_once, second_client, "Second Client")
            responses = [first.result(timeout=90), second.result(timeout=90)]

    assert sorted(response.status_code for response in responses) == [200, 403]

    db_session.expire_all()
    signatures = (
        db_session.query(JournalSignatureORM)
        .filter(
            JournalSignatureORM.company_id == company_id,
            JournalSignatureORM.journal_id == uuid.UUID(journal_id),
        )
        .all()
    )
    journal = (
        db_session.query(JournalORM)
        .filter(
            JournalORM.company_id == company_id,
            JournalORM.id == uuid.UUID(journal_id),
        )
        .one()
    )
    assert len(signatures) == 1
    assert journal.status == JournalStatus.ARCHIVED
    assert journal.signer_name == signatures[0].signer_name


def test_journal_admin_endpoints_forbidden_for_installer_role(client_installer):
    list_resp = client_installer.get("/api/v1/admin/journals")
    assert list_resp.status_code == 403, list_resp.text
    assert list_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    create_resp = client_installer.post(
        "/api/v1/admin/journals",
        json={"project_id": str(uuid.uuid4())},
    )
    assert create_resp.status_code == 403, create_resp.text
    assert create_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


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
