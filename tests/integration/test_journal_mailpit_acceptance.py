"""Opt-in acceptance test: isolated test DB, real MinIO and local Mailpit only."""
from __future__ import annotations

import io
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfReader
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.integrations.storage.minio_client import get_minio
from app.integrations.storage.storage_service import StorageService
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import UserORM
from app.modules.journal.infrastructure.models import JournalSignatureORM
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.outbox.infrastructure.repositories import OutboxRepository
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.workers import outbox_worker


pytestmark = pytest.mark.skipif(
    os.getenv("DIMAX_JOURNAL_MAILPIT") != "1",
    reason="Requires isolated acceptance test DB, MinIO and Mailpit",
)

# Capture before the suite's autouse in-memory storage fixture is applied.
_REAL_STORAGE = {
    name: getattr(StorageService, name)
    for name in ("put_pdf", "get_pdf", "get_object_stream")
}


def _mailpit(path, *, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        "http://mailpit:8025/api/v1/" + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=15) as response:
        return response.read()


def _messages(subject):
    result = json.loads(_mailpit("messages?limit=200"))
    return [row for row in result["messages"] if row["Subject"] == subject]


def _received_mail(subject):
    deadline = time.monotonic() + 15
    matches = _messages(subject)
    while not matches and time.monotonic() < deadline:
        time.sleep(0.2)
        matches = _messages(subject)
    assert len(matches) == 1
    raw = _mailpit(f"message/{matches[0]['ID']}/raw")
    return BytesParser(policy=policy.default).parsebytes(raw)


@pytest.fixture(scope="module", autouse=True)
def isolated_services():
    # Run before function-scoped fixtures can insert anything into a database.
    assert os.getenv("APP_ENV") == "test"
    for database in (settings.DATABASE_URL, os.environ["TEST_DATABASE_URL"]):
        parsed = make_url(database)
        assert parsed.database == "dimax_acceptance_tests" and parsed.host == "db"
    assert settings.SMTP_HOST == "mailpit" and settings.SMTP_PORT == 1025
    assert not settings.SMTP_TLS and not settings.SMTP_USER
    assert settings.EMAIL_ENABLED and not settings.WHATSAPP_ENABLED
    assert settings.MINIO_ENDPOINT == "minio:9000"
    assert settings.MINIO_BUCKET == "acceptance" and not settings.MINIO_SECURE


@pytest.fixture()
def local_delivery(db_session, company_id, monkeypatch):
    assert db_session.get_bind().url.database == "dimax_acceptance_tests"
    for name, method in _REAL_STORAGE.items():
        monkeypatch.setattr(StorageService, name, staticmethod(method))

    test_company_id = company_id

    class CompanyOutboxRepository(OutboxRepository):
        def lock_next_batch(self, *, company_id=None, limit=20):
            return super().lock_next_batch(company_id=test_company_id, limit=limit)

    monkeypatch.setattr(outbox_worker, "OutboxRepository", CompanyOutboxRepository)
    monkeypatch.setattr(outbox_worker, "SessionLocal", sessionmaker(bind=db_session.get_bind()))


def _cleanup_delivery(*, company_id, journal_id, subjects):
    # Never clear a mailbox or bucket: remove only this fixture's artifacts.
    try:
        ids = [row["ID"] for label in subjects for row in _messages(label)]
        if ids:
            _mailpit("messages", method="DELETE", body={"IDs": ids})
        for label in subjects:
            assert not _messages(label)
    finally:
        if journal_id:
            prefix = f"journals/{company_id}/{journal_id}/"
            storage = get_minio()
            for obj in storage.list_objects(settings.MINIO_BUCKET, prefix=prefix, recursive=True):
                assert obj.object_name.startswith(prefix)
                storage.remove_object(settings.MINIO_BUCKET, obj.object_name)
            assert not list(storage.list_objects(settings.MINIO_BUCKET, prefix=prefix, recursive=True))


def test_signed_pdf_reaches_local_mailpit_unchanged(
    client_admin_real_uow, db_session, company_id, admin_user, make_door_type, local_delivery
):
    client = client_admin_real_uow
    project_name = f"QA MAILPIT {uuid.uuid4().hex[:12]}"
    subject = f"DIMAX signed work acceptance - {project_name}"
    invite_subject = f"QA invitation - {project_name}"
    project = ProjectORM(
        company_id=company_id, name=project_name,
        address="QA only / Building A / Floor 2",
        developer_company="QA Developer - not a real acceptance",
        contact_name="QA contact", contact_email="developer.qa@example.com",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.commit()
    door_type = make_door_type(name="QA Entrance door")
    db_session.add_all([
        DoorORM(
            company_id=company_id, project_id=project.id, door_type_id=door_type.id,
            unit_label=f"A-2-{201 + i}", our_price=Decimal("100.00"),
            status=DoorStatus.INSTALLED, is_locked=False,
            installed_at=datetime(2026, 9, 14, 13, 12, tzinfo=timezone.utc),
        ) for i in range(5)
    ])
    db_session.commit()
    admin_email = db_session.query(UserORM.email).filter(UserORM.id == admin_user.id).scalar()
    journal_id = None
    try:
        created = client.post("/api/v1/admin/journals", json={
            "project_id": str(project.id), "title": "QA work acceptance - TEST ONLY",
        })
        assert created.status_code == 200, created.text
        journal_id = str(uuid.UUID(created.json()["id"]))
        route = f"/api/v1/admin/journals/{journal_id}"
        notes = (
            "QA TEST ONLY - not a real acceptance.\n"
            "\u0414\u0432\u0435\u0440\u0438 \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u044b.\n"
            "\u05d3\u05dc\u05ea\u05d5\u05ea \u05d4\u05d5\u05ea\u05e7\u05e0\u05d5.\n"
            "Literal characters: <inspection> & completed."
        )
        patched = client.patch(route, json={"notes": notes})
        assert patched.status_code == 200, patched.text
        draft = client.get(route + "/pdf")
        assert draft.status_code == 200, draft.text
        assert draft.content.startswith(b"%PDF")
        ready = client.post(route + "/mark-ready")
        assert ready.status_code == 200, ready.text
        token = ready.json()["public_token"]
        signing_url = ready.json()["signing_url"]
        invitation = client.post(route + "/send", json={
            "email_to": project.contact_email, "subject": invite_subject,
            "message": "QA TEST ONLY - review the attached document.",
            "send_email": True, "send_whatsapp": False,
        })
        assert invitation.status_code == 200, invitation.text
        assert invitation.json()["public_url"] == signing_url
        invitation_id = uuid.UUID(invitation.json()["outbox_ids"]["email"])
        assert invitation.json()["outbox_ids"]["whatsapp"] is None
        assert signing_url.startswith(settings.PUBLIC_APP_BASE_URL.rstrip("/") + "/acceptance/")
        unsigned_content = StorageService.get_pdf(object_key=invitation.json()["object_key"])
        assert outbox_worker.run_once(limit=1) == 1
        invitation_row = db_session.get(OutboxMessageORM, invitation_id)
        assert invitation_row is not None
        assert invitation_row.company_id == company_id
        assert invitation_row.correlation_id == uuid.UUID(journal_id)
        assert invitation_row.channel.value == "EMAIL"
        assert invitation_row.status.value == "SENT"
        assert invitation_row.payload["subject"] == invite_subject
        invitation_mail = _received_mail(invite_subject)
        invitation_body = invitation_mail.get_body(preferencelist=("plain",)).get_content()
        assert signing_url in invitation_body
        assert "/api/v1/public/journals/" not in invitation_body
        invitation_attachments = list(invitation_mail.iter_attachments())
        assert len(invitation_attachments) == 1
        assert invitation_attachments[0].get_payload(decode=True) == unsigned_content
        signed = client.post(f"/api/v1/public/journals/{token}/sign", json={
            "signer_name": "QA TEST SIGNER",
            "signature_payload": {
                "version": 1, "viewport": {"width": 320, "height": 120},
                "strokes": [[
                    {"x": 25, "y": 75}, {"x": 55, "y": 35},
                    {"x": 70, "y": 70}, {"x": 130, "y": 45},
                    {"x": 180, "y": 60}, {"x": 260, "y": 40},
                ]],
            },
        })
        assert signed.status_code == 200, signed.text
        assert signed.json() == {"ok": True, "pdf_ready": True, "email_queued": True}
        archived = client.get(route + "/pdf")
        assert archived.status_code == 200, archived.text
        assert archived.content != draft.content
        text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(archived.content)).pages)
        assert "QA TEST SIGNER" in text and "14.09.2026 16:12" in text
        assert "<inspection> & completed." in text

        db_session.expire_all()
        message = db_session.query(OutboxMessageORM).filter(
            OutboxMessageORM.company_id == company_id,
            OutboxMessageORM.correlation_id == uuid.UUID(journal_id),
            OutboxMessageORM.payload["delivery_reason"].as_string() == "SIGNED_JOURNAL",
        ).one()
        assert message.payload["delivery_reason"] == "SIGNED_JOURNAL"
        assert message.payload["to_email"] == project.contact_email
        assert message.payload["cc_emails"] == [admin_email]
        assert message.payload["object_key"].endswith("_signed.pdf")
        draft_key = f"journals/{company_id}/{journal_id}/journal_{journal_id}.pdf"
        assert StorageService.get_pdf(object_key=draft_key) == unsigned_content
        project.name = "Changed after QA signing"
        db_session.commit()
        exported = client.post(route + "/export-pdf")
        assert exported.status_code == 200, exported.text
        assert StorageService.get_pdf(object_key=exported.json()["file_path"]) == archived.content

        assert outbox_worker.run_once(limit=1) == 1
        assert outbox_worker.run_once(limit=1) == 0
        db_session.refresh(message)
        assert message.status.value == "SENT"
        details = client.get(route)
        assert details.status_code == 200, details.text
        assert details.json()["email_delivery_status"] == "DELIVERED"
        mail = _received_mail(subject)
        assert [address for _, address in getaddresses(mail.get_all("To", []))] == ["developer.qa@example.com"]
        assert [address for _, address in getaddresses(mail.get_all("Cc", []))] == [admin_email]
        attachments = list(mail.iter_attachments())
        assert len(attachments) == 1
        assert attachments[0].get_content_type() == "application/pdf"
        assert attachments[0].get_filename().endswith(".pdf")
        assert sha256(attachments[0].get_payload(decode=True)).digest() == sha256(archived.content).digest()
        output_dir = os.getenv("DIMAX_JOURNAL_QA_DIR")
        if output_dir:
            output = Path(output_dir).resolve()
            assert output == Path("/qa") and output.is_dir()
            (output / "qa-unsigned.pdf").write_bytes(unsigned_content)
            (output / "qa-signed.pdf").write_bytes(archived.content)
        print("MAILPIT PASS: signed PDF SHA256=" + sha256(archived.content).hexdigest())
    finally:
        _cleanup_delivery(
            company_id=company_id, journal_id=journal_id, subjects=(subject, invite_subject),
        )


def test_synced_installer_work_is_signed_and_delivered_without_duplicates(
    client_raw, db_session, company_id, admin_user, installer_user,
    make_user, make_installer, make_door_type, local_delivery,
):
    client = client_raw
    assert not client.app.dependency_overrides
    installer = make_installer(full_name="QA signing installer")
    installer.user_id = installer_user.id
    other_user = make_user()
    other_installer = make_installer(full_name="QA other installer")
    other_installer.user_id = other_user.id
    db_session.commit()

    def login(user_id):
        user = db_session.get(UserORM, user_id)
        response = client.post("/api/v1/auth/login", json={
            "company_id": str(company_id), "email": user.email,
            "password": "secret123",  # gitleaks:allow - fixture credential
            "device_id": f"qa-journal-{user_id}",
        })
        assert response.status_code == 200, response.text
        assert response.json()["user"]["id"] == str(user_id)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    admin_headers = login(admin_user.id)
    installer_headers = login(installer_user.id)
    other_headers = login(other_user.id)
    admin_email = db_session.get(UserORM, admin_user.id).email
    completed_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    project = ProjectORM(
        company_id=company_id, name=f"QA SYNC JOURNAL {uuid.uuid4().hex[:12]}",
        address="QA only / Building A / Floor 2",
        developer_company="QA ONLY - not a real acceptance",
        contact_name="QA contact", contact_email="developer.qa@example.com",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.commit()
    door_type = make_door_type(name="QA Entrance")
    rate = client.post("/api/v1/admin/installer-rates", headers=admin_headers, json={
        "installer_id": str(installer.id), "door_type_id": str(door_type.id),
        "price": "250.00", "effective_from": (completed_at - timedelta(days=1)).isoformat(),
    })
    assert rate.status_code == 201, rate.text
    doors = [
        DoorORM(
            company_id=company_id, project_id=project.id, door_type_id=door_type.id,
            unit_label=label, our_price=Decimal("400.00"), installer_id=assigned,
            status=status, is_locked=status == DoorStatus.INSTALLED, version=0,
            installed_at=completed_at if status == DoorStatus.INSTALLED else None,
        )
        for label, assigned, status in (
            ("QA-OWN-201", installer.id, DoorStatus.NOT_INSTALLED),
            ("QA-PENDING-202", installer.id, DoorStatus.NOT_INSTALLED),
            ("QA-OTHER-203", other_installer.id, DoorStatus.INSTALLED),
        )
    ]
    db_session.add_all(doors)
    db_session.commit()
    own_door, pending_door, other_door = doors
    subject = f"DIMAX signed work acceptance - {project.name}"
    journal_id = None
    try:
        for base_version, status in enumerate(("IN_PROGRESS", "INSTALLED")):
            item = {
                "id": str(uuid.uuid4()), "entity_type": "door",
                "entity_id": str(own_door.id), "operation_type": "DOOR_SET_STATUS",
                "project_id": str(project.id), "base_version": base_version,
                "happened_at": completed_at.isoformat(),
                "payload": {"door_id": str(own_door.id), "status": status},
            }
            batch = {"device_id": "qa-offline-journal", "items": [item]}
            # A lost response makes mobile retry the same durable outbox item.
            for _attempt in range(2):
                synced = client.post(
                    "/api/v1/installer/sync-queue/batch", headers=installer_headers, json=batch,
                )
                assert synced.status_code == 200, synced.text
                result = synced.json()["results"][0]
                assert result["status"] == "APPLIED", result
                assert result["new_version"] == base_version + 1

        db_session.expire_all()
        assert own_door.status == DoorStatus.INSTALLED and own_door.version == 2
        assert own_door.installed_at == completed_at
        assert pending_door.status == DoorStatus.NOT_INSTALLED
        assert other_door.version == 0
        ledger = db_session.query(CompletedWorkORM).filter_by(company_id=company_id).one()
        assert ledger.door_id == own_door.id and ledger.installer_id == installer.id
        assert ledger.amount_snapshot == Decimal("250.00")
        earnings = client.get("/api/v1/installer/earnings/summary", headers=installer_headers, params={
            "period": "day", "date": completed_at.astimezone(ZoneInfo("Asia/Jerusalem")).date().isoformat(),
        })
        assert earnings.status_code == 200, earnings.text
        assert Decimal(earnings.json()["total"]) == Decimal("250.00")
        assert earnings.json()["jobs_count"] == 1
        admin_ledger = client.get("/api/v1/admin/earnings/ledger", headers=admin_headers, params={
            "project_id": str(project.id), "installer_id": str(installer.id),
        })
        assert admin_ledger.status_code == 200, admin_ledger.text
        assert admin_ledger.json()["total"] == 1
        assert admin_ledger.json()["items"][0]["id"] == str(ledger.id)
        assert Decimal(admin_ledger.json()["items"][0]["amount_snapshot"]) == Decimal("250.00")

        prepared = client.post("/api/v1/installer/journals/prepare", headers=installer_headers, json={
            "project_id": str(project.id), "pdf_locale": "en",
        })
        assert prepared.status_code == 200, prepared.text
        journal_id = str(uuid.UUID(prepared.json()["id"]))
        route = f"/api/v1/installer/journals/{journal_id}"
        admin_route = f"/api/v1/admin/journals/{journal_id}"
        assert prepared.json()["can_submit"] is True
        assert [row["unit_label"] for row in prepared.json()["doors"]] == ["QA-OWN-201"]
        assert prepared.json()["completed_doors"] == 1
        assert prepared.json()["completed_addons"] == 0
        assert client.get(route).status_code == 401
        assert client.get(route, headers=other_headers).status_code == 404
        assert client.get(admin_route, headers=installer_headers).status_code == 403
        assert client.post(route + "/pdf-link", headers=installer_headers).status_code == 409
        repeated = client.post("/api/v1/installer/journals/prepare", headers=installer_headers, json={
            "project_id": str(project.id), "pdf_locale": "en",
        })
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["id"] == journal_id
        snapshot = client.get(admin_route + "/snapshot", headers=admin_headers)
        assert snapshot.status_code == 200, snapshot.text
        assert [row["unit_label"] for row in snapshot.json()["items"]] == ["QA-OWN-201"]

        ready = client.post(route + "/mark-ready", headers=installer_headers)
        assert ready.status_code == 200, ready.text
        signing_url = ready.json()["signing_url"]
        assert signing_url.startswith(settings.PUBLIC_APP_BASE_URL.rstrip("/") + "/acceptance/")
        token = signing_url.rsplit("/", 1)[-1]
        assert client.post(route + "/refresh", headers=installer_headers).status_code == 409
        assert db_session.query(OutboxMessageORM).filter_by(company_id=company_id).count() == 0
        public_document = client.get(f"/api/v1/public/journals/{token}")
        assert public_document.status_code == 200, public_document.text
        assert [row["unit_label"] for row in public_document.json()["items"]] == ["QA-OWN-201"]

        signature = {
            "signer_name": "QA SYNTHETIC SIGNER - TEST ONLY",
            "signature_payload": {
                "version": 1, "viewport": {"width": 320, "height": 120},
                "strokes": [[{"x": 20, "y": 70}, {"x": 140, "y": 35}]],
            },
        }
        signed = client.post(f"/api/v1/public/journals/{token}/sign", json=signature)
        assert signed.status_code == 200, signed.text
        assert signed.json() == {"ok": True, "pdf_ready": True, "email_queued": True}
        retry = client.post(f"/api/v1/public/journals/{token}/sign", json=signature)
        assert retry.status_code == 403, retry.text
        db_session.expire_all()
        assert db_session.query(JournalSignatureORM).filter_by(company_id=company_id).count() == 1
        message = db_session.query(OutboxMessageORM).filter_by(company_id=company_id).one()
        assert message.correlation_id == uuid.UUID(journal_id)
        assert message.payload["delivery_reason"] == "SIGNED_JOURNAL"
        assert message.payload["to_email"] == project.contact_email
        assert message.payload["cc_emails"] == [admin_email]
        assert message.status.value == "PENDING"

        archived = client.get(admin_route + "/pdf", headers=admin_headers)
        assert archived.status_code == 200, archived.text
        assert archived.content.startswith(b"%PDF")
        pdf_text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(archived.content)).pages)
        assert signature["signer_name"] in pdf_text and "QA-OWN-201" in pdf_text
        assert "QA-PENDING-202" not in pdf_text and "QA-OTHER-203" not in pdf_text
        assert client.post(route + "/pdf-link", headers=other_headers).status_code == 404
        shared = client.post(route + "/pdf-link", headers=installer_headers)
        assert shared.status_code == 200, shared.text
        parsed = urlsplit(shared.json()["url"])
        downloaded = client.get(parsed.path + "?" + parsed.query)
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.content == archived.content
        assert outbox_worker.run_once(limit=20) == 1
        assert outbox_worker.run_once(limit=20) == 0
        for path, headers in ((route, installer_headers), (admin_route, admin_headers)):
            details = client.get(path, headers=headers)
            assert details.status_code == 200, details.text
            assert details.json()["status"] == "ARCHIVED"
            assert details.json()["email_delivery_status"] == "DELIVERED"
            assert details.json()["signer_name"] == signature["signer_name"]

        mail = _received_mail(subject)
        assert [address for _, address in getaddresses(mail.get_all("To", []))] == [project.contact_email]
        assert [address for _, address in getaddresses(mail.get_all("Cc", []))] == [admin_email]
        attachments = list(mail.iter_attachments())
        assert len(attachments) == 1
        assert attachments[0].get_content_type() == "application/pdf"
        assert attachments[0].get_payload(decode=True) == archived.content
        db_session.expire_all()
        assert db_session.query(CompletedWorkORM).filter_by(company_id=company_id).count() == 1
        assert db_session.query(OutboxMessageORM).filter_by(company_id=company_id).count() == 1
        print("SYNC JOURNAL PASS: signed PDF SHA256=" + sha256(archived.content).hexdigest())
    finally:
        _cleanup_delivery(company_id=company_id, journal_id=journal_id, subjects=(subject,))
