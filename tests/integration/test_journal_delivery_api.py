from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from pypdf import PdfReader
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.integrations.storage.storage_service import StorageService
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.audit.infrastructure.repositories import AuditRepository
from app.modules.files.application.service import FileTokenService
from app.modules.files.infrastructure.models import (
    FileDownloadEventORM,
    FileDownloadTokenORM,
)
from app.modules.journal.infrastructure.models import (
    JournalAddonItemORM,
    JournalFileORM,
    JournalORM,
)
from app.modules.outbox.domain.enums import OutboxChannel
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.shared.domain.errors import ValidationError
from app.workers import outbox_worker


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch, db_session, company_id):
    from sqlalchemy.orm import sessionmaker
    from app.modules.outbox.infrastructure.repositories import OutboxRepository

    # Exercise channel behavior independently of the local stack configuration.
    monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "WHATSAPP_ENABLED", True)
    test_company_id = company_id

    class CompanyOutboxRepository(OutboxRepository):
        def lock_next_batch(self, *, company_id=None, limit=20):
            return super().lock_next_batch(company_id=test_company_id, limit=limit)

    monkeypatch.setattr(outbox_worker, "OutboxRepository", CompanyOutboxRepository)
    monkeypatch.setattr(
        outbox_worker, "SessionLocal", sessionmaker(bind=db_session.get_bind())
    )
    storage: dict[str, bytes] = {}

    class _Obj:
        def __init__(self, payload: bytes) -> None:
            self._buf = io.BytesIO(payload)

        def read(self, size: int = -1) -> bytes:
            return self._buf.read(size)

        def close(self) -> None:
            self._buf.close()

        def release_conn(self) -> None:
            return None

    def _put_pdf(*, object_key: str, content: bytes) -> None:
        storage[object_key] = content

    def _get_pdf(*, object_key: str) -> bytes:
        return storage[object_key]

    def _get_object_stream(*, bucket: str, object_key: str):
        _ = bucket
        return _Obj(payload=storage[object_key])

    monkeypatch.setattr(StorageService, "put_pdf", staticmethod(_put_pdf))
    monkeypatch.setattr(StorageService, "get_pdf", staticmethod(_get_pdf))
    monkeypatch.setattr(
        StorageService,
        "get_object_stream",
        staticmethod(_get_object_stream),
    )


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


def _create_journal(
    client_admin_real_uow,
    db_session,
    *,
    project_id: uuid.UUID,
    pdf_locale: str = "en",
) -> str:
    resp = client_admin_real_uow.post(
        "/api/v1/admin/journals",
        json={
            "project_id": str(project_id),
            "title": "Delivery Journal",
            "pdf_locale": pdf_locale,
        },
    )
    assert resp.status_code == 200, resp.text
    journal_id = uuid.UUID(resp.json()["id"])
    project = db_session.query(ProjectORM).filter(ProjectORM.id == project_id).one()
    db_session.add(
        JournalAddonItemORM(
            company_id=project.company_id,
            journal_id=journal_id,
            addon_fact_id=uuid.uuid4(),
            addon_type_id=uuid.uuid4(),
            addon_name="Delivery test completed work",
            unit="pcs",
            qty_done=Decimal("1.00"),
            done_at=datetime.now(timezone.utc),
            comment=None,
        )
    )
    db_session.commit()
    return str(journal_id)


def test_journal_send_enqueues_outbox_and_sets_pending_statuses(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Send Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(
        client_admin_real_uow, db_session, project_id=project.id
    )

    mark_ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert mark_ready_resp.status_code == 200, mark_ready_resp.text

    send_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "email_to": "client@example.com",
            "whatsapp_to": "+15551234567",
            "subject": "Delivery Subject",
            "message": "Delivery message",
            "send_email": True,
            "send_whatsapp": True,
        },
    )
    assert send_resp.status_code == 200, send_resp.text

    body = send_resp.json()
    assert body["ok"] is True
    assert body["enqueued"]["email"] is True
    assert body["enqueued"]["whatsapp"] is True
    assert "email" in body["outbox_ids"]
    assert "whatsapp" in body["outbox_ids"]
    signing_url = mark_ready_resp.json()["signing_url"]
    assert body["public_url"] == signing_url
    assert signing_url.startswith(settings.PUBLIC_APP_BASE_URL.rstrip("/") + "/acceptance/")

    journal_uuid = uuid.UUID(journal_id)
    email_msg = (
        db_session.query(OutboxMessageORM)
        .filter(
            OutboxMessageORM.company_id == company_id,
            OutboxMessageORM.correlation_id == journal_uuid,
            OutboxMessageORM.channel == OutboxChannel.EMAIL,
        )
        .order_by(OutboxMessageORM.created_at.desc())
        .first()
    )
    whatsapp_msg = (
        db_session.query(OutboxMessageORM)
        .filter(
            OutboxMessageORM.company_id == company_id,
            OutboxMessageORM.correlation_id == journal_uuid,
            OutboxMessageORM.channel == OutboxChannel.WHATSAPP,
        )
        .order_by(OutboxMessageORM.created_at.desc())
        .first()
    )

    assert email_msg is not None
    assert whatsapp_msg is not None
    assert email_msg.channel == OutboxChannel.EMAIL
    assert email_msg.payload["to_email"] == "client@example.com"
    assert email_msg.payload["subject"] == "Delivery Subject"
    assert "Attached: journal PDF." in email_msg.payload["body_text"]
    assert "Public link:" in email_msg.payload["body_text"]
    assert signing_url in email_msg.payload["body_text"]
    assert "/api/v1/public/journals/" not in email_msg.payload["body_text"]

    assert whatsapp_msg.channel == OutboxChannel.WHATSAPP
    assert whatsapp_msg.payload["to_phone"] == "+15551234567"
    assert "media_url" in whatsapp_msg.payload
    assert whatsapp_msg.payload["fallback_email"] is None
    assert "fallback_subject" in whatsapp_msg.payload
    assert "fallback_body_text" in whatsapp_msg.payload
    assert "object_key" in whatsapp_msg.payload
    assert signing_url in whatsapp_msg.payload["body_text"]
    assert signing_url in whatsapp_msg.payload["fallback_body_text"]
    assert whatsapp_msg.payload["media_url"].startswith(
        settings.PUBLIC_BASE_URL + "/api/v1/public/files/"
    )

    journal_resp = client_admin_real_uow.get(f"/api/v1/admin/journals/{journal_id}")
    assert journal_resp.status_code == 200, journal_resp.text
    journal_body = journal_resp.json()
    assert journal_body["email_delivery_status"] == "PENDING"
    assert journal_body["whatsapp_delivery_status"] == "PENDING"

    wa_token = (
        db_session.query(FileDownloadTokenORM)
        .filter(
            FileDownloadTokenORM.company_id == company_id,
            FileDownloadTokenORM.audience == "+15551234567",
        )
        .order_by(FileDownloadTokenORM.created_at.desc())
        .first()
    )
    assert wa_token is not None
    assert wa_token.uses_left == 2


@pytest.mark.parametrize(
    ("send_email", "send_whatsapp"),
    [(True, False), (False, True), (True, True)],
    ids=["email", "whatsapp", "both"],
)
def test_journal_send_ids_match_queue_and_audit_on_each_request(
    client_admin_real_uow, db_session, company_id, send_email, send_whatsapp
):
    project = _create_project(db_session, company_id=company_id, name="Send IDs")
    journal_id = _create_journal(
        client_admin_real_uow, db_session, project_id=project.id
    )
    journal_uuid = uuid.UUID(journal_id)
    expected_channels = {"email": send_email, "whatsapp": send_whatsapp}
    previous_ids = set()
    for request_number in range(1, 3):
        response = client_admin_real_uow.post(
            f"/api/v1/admin/journals/{journal_id}/send",
            json={
                "email_to": "queue-qa@example.com",
                "whatsapp_to": "+15551234567",
                "send_email": send_email,
                "send_whatsapp": send_whatsapp,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["enqueued"] == expected_channels
        current_ids = set()
        for channel, enabled in expected_channels.items():
            message_id = body["outbox_ids"][channel]
            if not enabled:
                assert message_id is None
                continue
            parsed_id = uuid.UUID(message_id)
            assert str(parsed_id) == message_id
            row = db_session.get(OutboxMessageORM, parsed_id)
            assert row is not None
            assert row.company_id == company_id
            assert row.correlation_id == journal_uuid
            assert row.channel.value == channel.upper()
            assert row.payload["object_key"] == body["object_key"]
            current_ids.add(parsed_id)
        assert len(current_ids) == sum(expected_channels.values())
        assert current_ids.isdisjoint(previous_ids)
        previous_ids.update(current_ids)
        audits = db_session.query(AuditLogORM).filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_id == journal_uuid,
            AuditLogORM.action == "JOURNAL_SEND_REQUESTED",
        ).all()
        assert len(audits) == request_number
        matching = [row for row in audits if row.after["outbox_ids"] == body["outbox_ids"]]
        assert len(matching) == 1
        assert matching[0].after["enqueued"] == expected_channels
        journal = client_admin_real_uow.get(f"/api/v1/admin/journals/{journal_id}")
        assert journal.status_code == 200, journal.text
        for channel in expected_channels:
            key = f"{channel}_delivery_status"
            assert matching[0].after[key] == journal.json()[key]
        queued_ids = {
            row.id for row in db_session.query(OutboxMessageORM).filter(
                OutboxMessageORM.company_id == company_id,
                OutboxMessageORM.correlation_id == journal_uuid,
            ).all()
        }
        assert queued_ids == previous_ids


@pytest.mark.parametrize("failure", ["whatsapp_recipient", "whatsapp_token", "audit"])
def test_journal_send_rolls_back_queue_tokens_statuses_and_audit(
    client_admin_real_uow, db_session, company_id, monkeypatch, failure
):
    client = client_admin_real_uow
    project = _create_project(db_session, company_id=company_id, name="Send rollback")
    journal_id = _create_journal(client, db_session, project_id=project.id)
    journal_uuid = uuid.UUID(journal_id)
    route = f"/api/v1/admin/journals/{journal_id}"
    before = client.get(route)
    assert before.status_code == 200, before.text
    injected_failures = []

    if failure == "whatsapp_token":
        create_token = FileTokenService.create_token_for_object

        def fail_after_token(uow, **kwargs):
            create_token(uow, **kwargs)
            # Force pending SQL writes before failing, so rollback is exercised.
            uow.session.flush()
            injected_failures.append("whatsapp_token")
            raise ValidationError("QA token preparation failure")

        monkeypatch.setattr(
            FileTokenService, "create_token_for_object", staticmethod(fail_after_token)
        )
    elif failure == "audit":
        add_audit = AuditRepository.add

        def fail_after_audit(self, row):
            add_audit(self, row)
            if row.action == "JOURNAL_SEND_REQUESTED":
                self.session.flush()
                injected_failures.append("audit")
                raise ValidationError("QA audit failure")

        monkeypatch.setattr(AuditRepository, "add", fail_after_audit)

    response = client.post(route + "/send", json={
        "email_to": "queue-qa@example.com",
        "whatsapp_to": None if failure == "whatsapp_recipient" else "+15551234567",
        "send_email": True,
        "send_whatsapp": True,
    })
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert injected_failures == ([] if failure == "whatsapp_recipient" else [failure])
    db_session.expire_all()
    assert db_session.query(OutboxMessageORM).filter(
        OutboxMessageORM.company_id == company_id,
        OutboxMessageORM.correlation_id == journal_uuid,
    ).count() == 0
    assert db_session.query(FileDownloadTokenORM).filter(
        FileDownloadTokenORM.company_id == company_id,
    ).count() == 0
    assert db_session.query(JournalFileORM).filter(
        JournalFileORM.company_id == company_id,
        JournalFileORM.journal_id == journal_uuid,
    ).count() == 0
    assert db_session.query(AuditLogORM).filter(
        AuditLogORM.company_id == company_id,
        AuditLogORM.entity_id == journal_uuid,
        AuditLogORM.action == "JOURNAL_SEND_REQUESTED",
    ).count() == 0
    after = client.get(route)
    assert after.status_code == 200, after.text
    for channel in ("email", "whatsapp"):
        key = f"{channel}_delivery_status"
        assert after.json()[key] == before.json()[key]


def test_journal_send_uses_backend_template_preview_when_requested(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Template Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(
        client_admin_real_uow, db_session, project_id=project.id
    )

    create_template_resp = client_admin_real_uow.post(
        "/api/v1/admin/settings/communication-templates",
        json={
            "name": "Template Delivery Notice",
            "subject": "Delivery for {{project_name}}",
            "message": "Review {{journal_title}} via {{public_url}}",
            "send_email": True,
            "send_whatsapp": False,
            "is_active": True,
        },
    )
    assert create_template_resp.status_code == 201, create_template_resp.text
    template_id = create_template_resp.json()["id"]

    mark_ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert mark_ready_resp.status_code == 200, mark_ready_resp.text

    send_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "template_id": template_id,
            "email_to": "templated@example.com",
            "send_email": True,
            "send_whatsapp": False,
        },
    )
    assert send_resp.status_code == 200, send_resp.text

    journal_uuid = uuid.UUID(journal_id)
    email_msg = (
        db_session.query(OutboxMessageORM)
        .filter(
            OutboxMessageORM.company_id == company_id,
            OutboxMessageORM.correlation_id == journal_uuid,
            OutboxMessageORM.channel == OutboxChannel.EMAIL,
        )
        .order_by(OutboxMessageORM.created_at.desc())
        .first()
    )
    assert email_msg is not None
    assert project.name in email_msg.payload["subject"]
    assert "Delivery Journal" in email_msg.payload["body_text"]
    assert "Public link:" in email_msg.payload["body_text"]
    signing_url = mark_ready_resp.json()["signing_url"]
    assert f"via {signing_url}" in email_msg.payload["body_text"]
    assert "/api/v1/public/journals/" not in email_msg.payload["body_text"]
    assert email_msg.payload["template_id"] == template_id
    assert email_msg.payload["template_code"] == "template-delivery-notice"
    assert email_msg.payload["template_name"] == "Template Delivery Notice"


@pytest.mark.parametrize("state", ["draft", "expired", "signed"])
def test_manual_send_keeps_pdf_but_omits_unusable_signing_links(
    client_admin_real_uow, db_session, company_id, state
):
    client = client_admin_real_uow
    project = _create_project(db_session, company_id=company_id, name=f"Link {state}")
    journal_id = _create_journal(client, db_session, project_id=project.id)
    route = f"/api/v1/admin/journals/{journal_id}"
    ready = client.post(route + "/mark-ready") if state != "draft" else None
    if ready is not None:
        assert ready.status_code == 200, ready.text
    journal = db_session.query(JournalORM).filter(JournalORM.id == uuid.UUID(journal_id)).one()
    if state == "draft":
        journal.public_token = uuid.uuid4().hex
        journal.public_token_expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        db_session.commit()
    elif state == "expired":
        journal.public_token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()
    else:
        signed = client.post(f"/api/v1/public/journals/{journal.public_token}/sign", json={
            "signer_name": "QA Signer",
            "signature_payload": {
                "viewport": {"width": 320, "height": 120},
                "strokes": [[{"x": 20, "y": 70}, {"x": 140, "y": 35}]],
            },
        })
        assert signed.status_code == 200, signed.text
    archived_pdf = client.get(route + "/pdf") if state == "signed" else None
    template = client.post("/api/v1/admin/settings/communication-templates", json={
        "name": f"QA {state} invitation", "subject": "Review {{public_url}}",
        "message": "Review {{journal_title}} via {{public_url}}",
        "send_email": True, "send_whatsapp": True, "is_active": True,
    })
    assert template.status_code == 201, template.text
    sent = client.post(route + "/send", json={
        "template_id": template.json()["id"], "email_to": "qa@example.com",
        "whatsapp_to": "+15551234567", "send_email": True, "send_whatsapp": True,
    })
    assert sent.status_code == 200, sent.text
    assert sent.json()["public_url"] is None
    rows = db_session.query(OutboxMessageORM).filter(
        OutboxMessageORM.company_id == company_id,
        OutboxMessageORM.correlation_id == uuid.UUID(journal_id),
    ).all()
    messages = [row for row in rows if row.payload.get("template_id") == template.json()["id"]]
    assert len(messages) == 2
    for row in messages:
        subject_key = "subject" if row.channel == OutboxChannel.EMAIL else "fallback_subject"
        assert journal.public_token not in row.payload[subject_key]
        for key in ("body_text", "fallback_body_text"):
            body = row.payload.get(key, "")
            assert journal.public_token not in body
            assert "Public link:" not in body and "Journal link:" not in body
        content = StorageService.get_pdf(object_key=row.payload["object_key"])
        assert content.startswith(b"%PDF")
        if archived_pdf is not None:
            assert archived_pdf.status_code == 200
            assert content == archived_pdf.content


def test_whatsapp_failure_enqueues_email_fallback_when_enabled(
    client_admin_real_uow,
    db_session,
    company_id,
    monkeypatch,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Fallback Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(
        client_admin_real_uow, db_session, project_id=project.id
    )

    mark_ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert mark_ready_resp.status_code == 200, mark_ready_resp.text

    send_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "email_to": "fallback@example.com",
            "whatsapp_to": "+15557778888",
            "send_email": False,
            "send_whatsapp": True,
            "subject": "Fallback Subject",
            "message": "Fallback message",
        },
    )
    assert send_resp.status_code == 200, send_resp.text

    monkeypatch.setattr(settings, "WHATSAPP_FALLBACK_TO_EMAIL", True)

    def _raise_wa_error(**_kwargs):
        raise RuntimeError("twilio unavailable")

    monkeypatch.setattr(outbox_worker.wa_sender, "send", _raise_wa_error)

    processed = outbox_worker.run_once(limit=20)
    assert processed == 0

    journal_uuid = uuid.UUID(journal_id)
    fallback_email_msg = (
        db_session.query(OutboxMessageORM)
        .filter(
            OutboxMessageORM.company_id == company_id,
            OutboxMessageORM.correlation_id == journal_uuid,
            OutboxMessageORM.channel == OutboxChannel.EMAIL,
        )
        .order_by(OutboxMessageORM.created_at.desc())
        .first()
    )
    assert fallback_email_msg is not None
    assert fallback_email_msg.payload["to_email"] == "fallback@example.com"
    assert fallback_email_msg.payload["subject"] == "Fallback Subject"
    assert "object_key" in fallback_email_msg.payload


def test_journal_share_pdf_creates_download_token(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Share Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(
        client_admin_real_uow, db_session, project_id=project.id
    )

    share_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/pdf/share",
        json={
            "ttl_sec": 300,
            "uses": 4,
            "audience": "+15550001111",
        },
    )
    assert share_resp.status_code == 200, share_resp.text

    share_body = share_resp.json()
    parsed = urlparse(share_body["url"])
    token = parsed.path.rsplit("/", 1)[-1]
    aud_qs = parse_qs(parsed.query)

    assert token
    assert aud_qs.get("aud") == ["+15550001111"]
    assert share_body["ttl_sec"] == 300
    assert share_body["uses"] == 4

    row = (
        db_session.query(FileDownloadTokenORM)
        .filter(
            FileDownloadTokenORM.company_id == company_id,
            FileDownloadTokenORM.token == token,
        )
        .one()
    )
    assert row.uses_left == 4
    assert row.audience == "+15550001111"
    assert row.object_key.endswith(f"/{journal_id}/journal_{journal_id}.pdf")


def test_journal_pdf_download_streams_file_and_audits_download(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"PDF Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(
        client_admin_real_uow, db_session, project_id=project.id
    )

    pdf_resp = client_admin_real_uow.get(f"/api/v1/admin/journals/{journal_id}/pdf")
    assert pdf_resp.status_code == 200, pdf_resp.text
    assert pdf_resp.headers["content-type"].startswith("application/pdf")
    assert "attachment;" in pdf_resp.headers["content-disposition"]
    assert pdf_resp.content[:4] == b"%PDF"

    event = (
        db_session.query(FileDownloadEventORM)
        .filter(
            FileDownloadEventORM.company_id == company_id,
            FileDownloadEventORM.correlation_id == uuid.UUID(journal_id),
            FileDownloadEventORM.source == "ADMIN",
        )
        .order_by(FileDownloadEventORM.created_at.desc())
        .first()
    )
    assert event is not None
    assert event.file_name == f"journal_{journal_id}.pdf"


def test_journal_delivery_endpoints_forbidden_for_installer_role(client_installer):
    journal_id = uuid.uuid4()

    send_resp = client_installer.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "email_to": "client@example.com",
            "send_email": True,
            "send_whatsapp": False,
        },
    )
    assert send_resp.status_code == 403, send_resp.text
    assert send_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    share_resp = client_installer.post(
        f"/api/v1/admin/journals/{journal_id}/pdf/share",
        json={"ttl_sec": 300, "uses": 2},
    )
    assert share_resp.status_code == 403, share_resp.text
    assert share_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    pdf_resp = client_installer.get(f"/api/v1/admin/journals/{journal_id}/pdf")
    assert pdf_resp.status_code == 403, pdf_resp.text
    assert pdf_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_journal_delivery_validation_and_not_found(client_admin_real_uow):
    missing_id = uuid.uuid4()

    invalid_channels_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{missing_id}/send",
        json={
            "send_email": False,
            "send_whatsapp": False,
        },
    )
    assert invalid_channels_resp.status_code == 422, invalid_channels_resp.text
    assert invalid_channels_resp.json()["error"]["code"] == "VALIDATION_ERROR"

    share_validation_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{missing_id}/pdf/share",
        json={
            "ttl_sec": 1,
            "uses": 1,
        },
    )
    assert share_validation_resp.status_code == 422, share_validation_resp.text

    send_not_found_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{missing_id}/send",
        json={
            "send_email": False,
            "send_whatsapp": True,
            "whatsapp_to": "+15550002222",
        },
    )
    assert send_not_found_resp.status_code == 404, send_not_found_resp.text
    assert send_not_found_resp.json()["error"]["code"] == "NOT_FOUND"

    share_not_found_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{missing_id}/pdf/share",
        json={
            "ttl_sec": 300,
            "uses": 1,
        },
    )
    assert share_not_found_resp.status_code == 404, share_not_found_resp.text
    assert share_not_found_resp.json()["error"]["code"] == "NOT_FOUND"

    pdf_not_found_resp = client_admin_real_uow.get(
        f"/api/v1/admin/journals/{missing_id}/pdf"
    )
    assert pdf_not_found_resp.status_code == 404, pdf_not_found_resp.text
    assert pdf_not_found_resp.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("locale", ["en", "ru", "he"])
def test_journal_document_language_is_persisted_audited_and_locked_before_signing(
    client_admin_real_uow, db_session, company_id, locale
):
    client = client_admin_real_uow
    project = _create_project(db_session, company_id=company_id, name="QA PDF language")
    journal_id = _create_journal(client, db_session, project_id=project.id, pdf_locale=locale)
    route = f"/api/v1/admin/journals/{journal_id}"
    assert client.get(route).json()["pdf_locale"] == locale
    assert client.get(route + "/snapshot").json()["journal"]["pdf_locale"] == locale
    changed = {"en": "ru", "ru": "he", "he": "en"}[locale]
    updated = client.patch(route, json={"pdf_locale": changed})
    assert updated.status_code == 200, updated.text
    audit = db_session.query(AuditLogORM).filter(
        AuditLogORM.company_id == company_id,
        AuditLogORM.entity_id == uuid.UUID(journal_id),
        AuditLogORM.action == "JOURNAL_PDF_LANGUAGE_UPDATED",
    ).one()
    assert audit.before == {"pdf_locale": locale}
    assert audit.after == {"pdf_locale": changed}
    assert client.patch(route, json={"lock_header": True}).status_code == 200
    assert client.patch(route, json={"pdf_locale": locale}).status_code == 409
    assert client.patch(route, json={"lock_header": False}).status_code == 200
    ready = client.post(route + "/mark-ready")
    assert ready.status_code == 200, ready.text
    assert client.patch(route, json={"pdf_locale": locale}).status_code == 409
    token = ready.json()["public_token"]
    public = client.get(f"/api/v1/public/journals/{token}")
    assert public.status_code == 200, public.text
    assert public.json()["journal"]["pdf_locale"] == changed
    signed = client.post(f"/api/v1/public/journals/{token}/sign", json={
        "signer_name": "QA Signer",
        "signature_payload": {
            "viewport": {"width": 320, "height": 120},
            "strokes": [[{"x": 20, "y": 70}, {"x": 140, "y": 35}]],
        },
    })
    assert signed.status_code == 200, signed.text
    pdf = client.get(route + "/pdf")
    assert pdf.status_code == 200, pdf.text
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    expected = {"en": "Developer acceptance", "ru": "Приёмка застройщиком", "he": "אישור היזם"}
    assert expected[changed] in text
    assert client.patch(route, json={"pdf_locale": locale}).status_code == 409
    assert client.get(route + "/pdf").content == pdf.content


def test_journal_pdf_language_rejects_invalid_api_values_and_database_rows(
    client_admin_real_uow, db_session, company_id
):
    client = client_admin_real_uow
    project = _create_project(db_session, company_id=company_id, name="QA invalid language")
    journal_id = _create_journal(client, db_session, project_id=project.id)
    for locale in ("zz", "EN", "ru-RU", ""):
        assert client.post("/api/v1/admin/journals", json={
            "project_id": str(project.id), "pdf_locale": locale,
        }).status_code == 422
        assert client.patch(f"/api/v1/admin/journals/{journal_id}", json={
            "pdf_locale": locale,
        }).status_code == 422
    db_session.add(JournalORM(company_id=company_id, project_id=project.id, pdf_locale="zz"))
    with pytest.raises(IntegrityError, match="ck_journals_pdf_locale"):
        db_session.flush()
    db_session.rollback()
