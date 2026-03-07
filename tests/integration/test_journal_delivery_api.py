from __future__ import annotations

import io
import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.config import settings
from app.integrations.storage.storage_service import StorageService
from app.modules.files.infrastructure.models import (
    FileDownloadEventORM,
    FileDownloadTokenORM,
)
from app.modules.outbox.domain.enums import OutboxChannel
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.workers import outbox_worker


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
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
        status=ProjectStatus.OK,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _create_journal(client_admin_real_uow, *, project_id: uuid.UUID) -> str:
    resp = client_admin_real_uow.post(
        "/api/v1/admin/journals",
        json={
            "project_id": str(project_id),
            "title": "Delivery Journal",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


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
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)

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
    assert body["public_url"] is not None

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

    assert whatsapp_msg.channel == OutboxChannel.WHATSAPP
    assert whatsapp_msg.payload["to_phone"] == "+15551234567"
    assert "media_url" in whatsapp_msg.payload
    assert whatsapp_msg.payload["fallback_email"] is None
    assert "fallback_subject" in whatsapp_msg.payload
    assert "fallback_body_text" in whatsapp_msg.payload
    assert "object_key" in whatsapp_msg.payload

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
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)

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
    assert email_msg.payload["template_id"] == template_id
    assert email_msg.payload["template_code"] == "template-delivery-notice"
    assert email_msg.payload["template_name"] == "Template Delivery Notice"


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
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)

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
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)

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
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)

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
    assert send_resp.json()["error"]["code"] == "FORBIDDEN"

    share_resp = client_installer.post(
        f"/api/v1/admin/journals/{journal_id}/pdf/share",
        json={"ttl_sec": 300, "uses": 2},
    )
    assert share_resp.status_code == 403, share_resp.text
    assert share_resp.json()["error"]["code"] == "FORBIDDEN"

    pdf_resp = client_installer.get(f"/api/v1/admin/journals/{journal_id}/pdf")
    assert pdf_resp.status_code == 403, pdf_resp.text
    assert pdf_resp.json()["error"]["code"] == "FORBIDDEN"


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
