"""Opt-in: real PostgreSQL + loopback SMTP, synthetic signed work only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email import policy
from email.parser import BytesParser
import os
import socket
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.integrations.email.smtp_sender import SmtpEmailSender
from app.integrations.storage.storage_service import StorageService
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.journal.infrastructure.models import JournalORM, JournalSignatureORM, JournalDoorItemORM
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.outbox.infrastructure.repositories import OutboxRepository
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.workers import outbox_worker
from test_smtp_tls_transport import certificates, configure, capture_server  # noqa: F401


pytestmark = pytest.mark.skipif(
    os.getenv("DIMAX_OUTBOX_SMTP_ACCEPTANCE") != "1",
    reason="Requires the isolated outbox SMTP acceptance runner",
)


@pytest.fixture(scope="module", autouse=True)
def isolated_database():
    assert os.getenv("APP_ENV") == "test"
    for value in (settings.DATABASE_URL, os.environ["TEST_DATABASE_URL"]):
        url = make_url(value)
        assert url.host == "127.0.0.1" and url.database == "dimax_acceptance_tests"
        assert url.username == "outbox_acceptance"


@pytest.fixture
def signed_case(client_admin_real_uow, db_session, company_id, make_installer, make_door_type, monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "WHATSAPP_ENABLED", False)
    scope = company_id

    class ScopedOutbox(OutboxRepository):
        def lock_next_batch(self, *, company_id=None, limit=20):
            return super().lock_next_batch(company_id=scope, limit=limit)

    monkeypatch.setattr(outbox_worker, "OutboxRepository", ScopedOutbox)
    monkeypatch.setattr(outbox_worker, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(outbox_worker, "email_sender", SmtpEmailSender())
    project = ProjectORM(company_id=company_id, name="SMTP recovery TEST ONLY", address="Synthetic Building A",
                         contact_email="factory@dimax.example.com", status=ProjectStatus.OK)
    db_session.add(project)
    db_session.commit()
    installer = make_installer()
    door_type = make_door_type()
    now = datetime.now(timezone.utc)
    door = DoorORM(company_id=company_id, project_id=project.id, door_type_id=door_type.id,
                   unit_label="TEST-A-101", our_price=Decimal("9.01"), status=DoorStatus.INSTALLED,
                   installed_at=now, installer_id=installer.id, is_locked=False)
    db_session.add(door)
    db_session.commit()
    db_session.add(CompletedWorkORM(company_id=company_id, project_id=project.id, door_id=door.id,
                                   installer_id=installer.id, completed_at=now,
                                   rate_snapshot=Decimal("9.01"), amount_snapshot=Decimal("9.01")))
    db_session.commit()
    client = client_admin_real_uow
    created = client.post("/api/v1/admin/journals", json={"project_id": str(project.id), "pdf_locale": "en"})
    assert created.status_code == 200, created.text
    journal_id = UUID(created.json()["id"])
    ready = client.post(f"/api/v1/admin/journals/{journal_id}/mark-ready")
    assert ready.status_code == 200, ready.text
    token = ready.json()["public_token"]
    response = client.post(f"/api/v1/public/journals/{token}/sign", json={
        "signer_name": "SYNTHETIC SMTP TEST SIGNER",
        "signature_payload": {"version": 1, "viewport": {"width": 320, "height": 120},
                              "strokes": [[{"x": 20, "y": 80}, {"x": 60, "y": 30},
                                           {"x": 120, "y": 70}, {"x": 250, "y": 40}]]},
    })
    assert response.status_code == 200, response.text
    assert response.json()["email_queued"] is True
    db_session.expire_all()
    message = db_session.query(OutboxMessageORM).filter_by(company_id=company_id).one()
    assert message.payload["delivery_reason"] == "SIGNED_JOURNAL"
    return SimpleNamespace(client=client, session=db_session, company_id=company_id,
                           journal_id=journal_id, message_id=message.id,
                           payload=dict(message.payload), pdf=StorageService.get_pdf(object_key=message.payload["object_key"]))


def business_snapshot(case):
    case.session.expire_all()
    result = {}
    for model in (DoorORM, CompletedWorkORM, JournalSignatureORM, JournalDoorItemORM):
        result[model.__tablename__] = case.session.execute(
            select(model.__table__).where(model.company_id == case.company_id).order_by(model.id)
        ).all()
    journal = case.session.get(JournalORM, case.journal_id)
    result["signed_journal"] = (journal.status, journal.signed_at, journal.signer_name,
                                journal.snapshot_version, journal.lock_header, journal.lock_table, journal.lock_footer)
    assert len(result["completed_work"]) == 1
    assert len(result["journal_signatures"]) == 1
    return result


def message(case):
    case.session.expire_all()
    rows = case.session.query(OutboxMessageORM).filter_by(company_id=case.company_id).all()
    assert len(rows) == 1 and rows[0].id == case.message_id
    assert rows[0].payload == case.payload
    return rows[0]


def make_due(case):
    row = message(case)
    row.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    case.session.commit()


def assert_received(case, server):
    assert len(server.messages) == 1
    mail = BytesParser(policy=policy.default).parsebytes(server.messages[0])
    assert mail["To"] == case.payload["to_email"]
    assert mail["Cc"] == ", ".join(case.payload["cc_emails"])
    attachment, = mail.iter_attachments()
    assert attachment.get_payload(decode=True) == case.pdf


def test_connection_refused_then_recovery_preserves_signed_work(signed_case, certificates, configure):
    case = signed_case
    before = business_snapshot(case)
    with socket.socket() as offline:
        offline.bind(("127.0.0.1", 0))  # Reserved, but not listening: real connection refusal.
        port = offline.getsockname()[1]
        configure(SimpleNamespace(server_address=offline.getsockname()))
        assert outbox_worker.run_once() == 0
        row = message(case)
        assert row.status.value == "PENDING" and row.attempts == 1 and row.last_error
        assert row.scheduled_at > datetime.now(timezone.utc) and row.sent_at is None
        assert outbox_worker.run_once() == 0  # Backoff prevents immediate retry.
        assert message(case).attempts == 1
    assert business_snapshot(case) == before
    make_due(case)
    with capture_server(certificates, "valid", port=port) as server:
        assert outbox_worker.run_once() == 1  # New DB session reads the durable pending job.
        assert outbox_worker.run_once() == 0
    assert_received(case, server)
    assert message(case).status.value == "SENT"
    assert business_snapshot(case) == before
    journal = case.session.get(JournalORM, case.journal_id)
    assert journal.email_delivery_status.value == "DELIVERED" and journal.email_last_error is None


def test_exhausted_job_survives_and_admin_retries_same_job(signed_case, certificates, configure):
    case = signed_case
    before = business_snapshot(case)
    message(case).max_attempts = 2
    case.session.commit()
    with socket.socket() as offline:
        offline.bind(("127.0.0.1", 0))
        port = offline.getsockname()[1]
        configure(SimpleNamespace(server_address=offline.getsockname()))
        assert outbox_worker.run_once() == 0
        make_due(case)
        assert outbox_worker.run_once() == 0
        row = message(case)
        assert row.status.value == "FAILED" and row.attempts == 2
    with capture_server(certificates, "valid", port=port) as server:
        assert outbox_worker.run_once() == 0  # Restoring SMTP cannot resurrect exhausted jobs.
        retried = case.client.post(f"/api/v1/admin/outbox/{case.message_id}/retry",
                                   json={"reason": "Synthetic SMTP restored"})
        assert retried.status_code == 200, retried.text
        assert message(case).max_attempts == 3
        assert outbox_worker.run_once() == 1
        assert outbox_worker.run_once() == 0
        blocked = case.client.post(f"/api/v1/admin/outbox/{case.message_id}/retry",
                                   json={"reason": "Must not resend SENT job"})
        assert blocked.status_code == 422, blocked.text
    assert_received(case, server)
    assert business_snapshot(case) == before
    assert message(case).status.value == "SENT"
    assert case.session.query(AuditLogORM).filter_by(company_id=case.company_id, action="OUTBOX_RETRY").count() == 1


def test_commit_failure_can_repeat_email_but_not_business_actions(signed_case, certificates, configure, monkeypatch):
    case = signed_case
    before = business_snapshot(case)
    failed = False

    class FailCommitOnce(Session):
        def commit(self):
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError("Synthetic DB commit failure after SMTP acceptance")
            return super().commit()

    monkeypatch.setattr(outbox_worker, "SessionLocal", sessionmaker(bind=case.session.get_bind(), class_=FailCommitOnce))
    with capture_server(certificates, "valid") as server:
        configure(server)
        assert outbox_worker.run_once() == 0
        assert failed
        assert message(case).status.value == "PENDING"
        assert business_snapshot(case) == before
        assert outbox_worker.run_once() == 1
        assert outbox_worker.run_once() == 0
    assert len(server.messages) == 2  # SMTP is at-least-once, not exactly-once.
    assert message(case).status.value == "SENT"
    assert business_snapshot(case) == before
