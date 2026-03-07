from __future__ import annotations

import uuid

from app.core.config import settings
from app.modules.audit.infrastructure.models import AuditLogORM
from app.integrations.email.smtp_sender import SmtpEmailSender
from app.integrations.whatsapp.twilio_sender import TwilioWhatsAppSender
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


def _create_journal(client_admin_real_uow, *, project_id: uuid.UUID) -> str:
    resp = client_admin_real_uow.post(
        "/api/v1/admin/journals",
        json={
            "project_id": str(project_id),
            "title": "Communication Preview Journal",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_door_types_admin_crud_flow(client_admin_real_uow):
    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/door-types",
        json={
            "code": "single",
            "name": "Single Door",
            "is_active": True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    door_type_id = created["id"]
    assert created["code"] == "single"
    assert created["name"] == "Single Door"

    list_resp = client_admin_real_uow.get("/api/v1/admin/door-types")
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()
    assert any(x["id"] == door_type_id for x in items)

    update_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/door-types/{door_type_id}",
        json={"name": "Single Door v2", "is_active": False},
    )
    assert update_resp.status_code == 200, update_resp.text
    updated = update_resp.json()
    assert updated["name"] == "Single Door v2"
    assert updated["is_active"] is False

    get_resp = client_admin_real_uow.get(f"/api/v1/admin/door-types/{door_type_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == door_type_id

    delete_resp = client_admin_real_uow.delete(f"/api/v1/admin/door-types/{door_type_id}")
    assert delete_resp.status_code == 204, delete_resp.text

    list_after_delete = client_admin_real_uow.get("/api/v1/admin/door-types")
    assert list_after_delete.status_code == 200, list_after_delete.text
    assert all(x["id"] != door_type_id for x in list_after_delete.json())


def test_reasons_admin_crud_flow(client_admin_real_uow):
    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/reasons",
        json={
            "code": "missing-part",
            "name": "Missing Part",
            "is_active": True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    reason_id = created["id"]

    list_resp = client_admin_real_uow.get("/api/v1/admin/reasons")
    assert list_resp.status_code == 200, list_resp.text
    assert any(x["id"] == reason_id for x in list_resp.json())

    update_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/reasons/{reason_id}",
        json={"name": "Missing Part v2"},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["name"] == "Missing Part v2"

    get_resp = client_admin_real_uow.get(f"/api/v1/admin/reasons/{reason_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == reason_id

    delete_resp = client_admin_real_uow.delete(f"/api/v1/admin/reasons/{reason_id}")
    assert delete_resp.status_code == 204, delete_resp.text

    list_after_delete = client_admin_real_uow.get("/api/v1/admin/reasons")
    assert list_after_delete.status_code == 200, list_after_delete.text
    assert all(x["id"] != reason_id for x in list_after_delete.json())


def test_settings_company_and_integrations_endpoints(client_admin_real_uow):
    get_company = client_admin_real_uow.get("/api/v1/admin/settings/company")
    assert get_company.status_code == 200, get_company.text
    before = get_company.json()
    assert "id" in before
    assert "name" in before

    update_company = client_admin_real_uow.patch(
        "/api/v1/admin/settings/company",
        json={"name": "DIMAX GROUP UPDATED"},
    )
    assert update_company.status_code == 200, update_company.text
    updated = update_company.json()
    assert updated["id"] == before["id"]
    assert updated["name"] == "DIMAX GROUP UPDATED"

    get_integrations = client_admin_real_uow.get("/api/v1/admin/settings/integrations")
    assert get_integrations.status_code == 200, get_integrations.text
    body = get_integrations.json()
    for key in (
        "public_base_url",
        "smtp_configured",
        "email_enabled",
        "twilio_configured",
        "whatsapp_enabled",
        "whatsapp_fallback_to_email",
        "storage_configured",
        "waze_base_url",
        "waze_navigation_enabled",
        "file_token_ttl_sec",
        "file_token_uses",
        "journal_public_token_ttl_sec",
        "sync_warn_lag",
        "sync_danger_lag",
        "sync_warn_days_offline",
        "sync_danger_days_offline",
        "sync_project_auto_problem_enabled",
        "sync_project_auto_problem_days",
        "auth_login_rl_window_sec",
        "auth_login_rl_max_req",
        "auth_refresh_rl_window_sec",
        "auth_refresh_rl_max_req",
    ):
        assert key in body

    health_resp = client_admin_real_uow.get("/api/v1/admin/settings/integrations/health")
    assert health_resp.status_code == 200, health_resp.text
    health = health_resp.json()
    assert health["email"]["channel"] == "EMAIL"
    assert health["whatsapp"]["channel"] == "WHATSAPP"
    assert "ready" in health["email"]
    assert "ready" in health["whatsapp"]


def test_settings_communication_templates_crud_and_preview(
    client_admin_real_uow,
    db_session,
    company_id,
):
    list_resp = client_admin_real_uow.get(
        "/api/v1/admin/settings/communication-templates"
    )
    assert list_resp.status_code == 200, list_resp.text
    defaults = list_resp.json()["items"]
    assert len(defaults) >= 3
    assert any(item["code"] == "client-final-delivery" for item in defaults)

    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/settings/communication-templates",
        json={
            "name": "Customer Completion Notice",
            "subject": "Completion for {{project_name}}",
            "message": "Review {{journal_title}} at {{public_url}}",
            "send_email": True,
            "send_whatsapp": True,
            "is_active": True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["code"] == "customer-completion-notice"

    update_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/settings/communication-templates/{created['id']}",
        json={
            "name": "Customer Completion Notice v2",
            "send_whatsapp": False,
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    updated = update_resp.json()
    assert updated["name"] == "Customer Completion Notice v2"
    assert updated["send_whatsapp"] is False
    assert updated["code"] == "customer-completion-notice-v2"

    project = _create_project(
        db_session,
        company_id=company_id,
        name="Communications Project",
    )
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)
    mark_ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert mark_ready_resp.status_code == 200, mark_ready_resp.text

    preview_resp = client_admin_real_uow.post(
        "/api/v1/admin/settings/communication-templates/render-preview",
        json={
            "template_id": created["id"],
            "journal_id": journal_id,
        },
    )
    assert preview_resp.status_code == 200, preview_resp.text
    preview = preview_resp.json()
    assert "Communications Project" in preview["subject"]
    assert "Communication Preview Journal" in preview["message"]
    assert preview["variables"]["project_name"] == "Communications Project"
    assert preview["variables"]["public_url"] is not None

    delete_resp = client_admin_real_uow.delete(
        f"/api/v1/admin/settings/communication-templates/{created['id']}"
    )
    assert delete_resp.status_code == 204, delete_resp.text

    list_after = client_admin_real_uow.get(
        "/api/v1/admin/settings/communication-templates"
    )
    assert list_after.status_code == 200, list_after.text
    ids_after = {item["id"] for item in list_after.json()["items"]}
    assert created["id"] not in ids_after


def test_settings_integration_test_send_endpoints(
    client_admin_real_uow,
    db_session,
    company_id,
    admin_user,
    monkeypatch,
):
    email_calls: list[dict] = []
    whatsapp_calls: list[dict] = []

    def _fake_email_send(self, **kwargs):
        email_calls.append(kwargs)

    def _fake_whatsapp_send(self, **kwargs):
        whatsapp_calls.append(kwargs)
        return "SMTEST123"

    monkeypatch.setattr(SmtpEmailSender, "send", _fake_email_send)
    monkeypatch.setattr(TwilioWhatsAppSender, "send", _fake_whatsapp_send)
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC_TEST")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "auth-token")
    monkeypatch.setattr(settings, "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    monkeypatch.setattr(settings, "TWILIO_STATUS_CALLBACK_URL", "https://dimax.example.com/api/v1/webhooks/twilio/status")

    email_resp = client_admin_real_uow.post(
        "/api/v1/admin/settings/integrations/test-email",
        json={
            "to_email": "ops@example.com",
            "subject": "SMTP test",
            "message": "Health probe",
        },
    )
    assert email_resp.status_code == 200, email_resp.text
    assert email_resp.json()["channel"] == "EMAIL"
    assert email_calls[0]["to_email"] == "ops@example.com"
    assert email_calls[0]["subject"] == "SMTP test"

    whatsapp_resp = client_admin_real_uow.post(
        "/api/v1/admin/settings/integrations/test-whatsapp",
        json={
            "to_phone": "+15550001111",
            "message": "Twilio probe",
        },
    )
    assert whatsapp_resp.status_code == 200, whatsapp_resp.text
    body = whatsapp_resp.json()
    assert body["channel"] == "WHATSAPP"
    assert body["provider_message_id"] == "SMTEST123"
    assert whatsapp_calls[0]["to_phone_e164"] == "+15550001111"

    audit_actions = {
        row.action
        for row in db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.actor_user_id == admin_user.id,
            AuditLogORM.entity_type == "integration_channel",
            AuditLogORM.entity_id == company_id,
        )
        .all()
    }
    assert "INTEGRATION_TEST_EMAIL_SEND" in audit_actions
    assert "INTEGRATION_TEST_WHATSAPP_SEND" in audit_actions


def test_catalogs_and_settings_forbidden_for_installer_role(client_installer):
    endpoints = (
        "/api/v1/admin/door-types",
        "/api/v1/admin/reasons",
        "/api/v1/admin/settings/company",
        "/api/v1/admin/settings/integrations",
        "/api/v1/admin/settings/communication-templates",
    )
    for path in endpoints:
        resp = client_installer.get(path)
        assert resp.status_code == 403, f"{path}: {resp.text}"
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    for path, payload in (
        (
            "/api/v1/admin/settings/integrations/test-email",
            {"to_email": "ops@example.com"},
        ),
        (
            "/api/v1/admin/settings/integrations/test-whatsapp",
            {"to_phone": "+15550001111"},
        ),
    ):
        resp = client_installer.post(path, json=payload)
        assert resp.status_code == 403, f"{path}: {resp.text}"
        assert resp.json()["error"]["code"] == "FORBIDDEN"
