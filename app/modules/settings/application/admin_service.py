from __future__ import annotations

import re
import uuid

from app.core.config import settings
from app.integrations.email.smtp_sender import SmtpEmailSender
from app.integrations.whatsapp.twilio_sender import TwilioWhatsAppSender
from app.modules.settings.infrastructure.models import CommunicationTemplateORM
from app.shared.domain.errors import NotFound
from app.shared.domain.errors import ValidationError


DEFAULT_COMMUNICATION_TEMPLATES = (
    {
        "name": "Client Final Delivery",
        "subject": "Final delivery confirmation for {{project_name}}",
        "message": (
            "The delivery package for {{project_name}} is ready. "
            "Please review {{journal_title}}. {{public_url}}"
        ),
        "send_email": True,
        "send_whatsapp": False,
        "is_active": True,
    },
    {
        "name": "Site Manager Coordination",
        "subject": "Coordination for next visit at {{project_name}}",
        "message": (
            "Please confirm access, readiness and contact presence for "
            "{{project_name}} at {{project_address}}."
        ),
        "send_email": True,
        "send_whatsapp": True,
        "is_active": True,
    },
    {
        "name": "Installer Reminder",
        "subject": "Installer reminder for {{project_name}}",
        "message": (
            "Review the outstanding blockers and access conditions for "
            "{{project_name}} before the next visit."
        ),
        "send_email": False,
        "send_whatsapp": True,
        "is_active": True,
    },
)


class SettingsAdminService:
    @staticmethod
    def _ensure_default_templates(
        uow,
        *,
        company_id: uuid.UUID,
    ) -> None:
        if uow.settings.list_templates(company_id=company_id):
            return
        for item in DEFAULT_COMMUNICATION_TEMPLATES:
            row = CommunicationTemplateORM(
                company_id=company_id,
                code=SettingsAdminService._ensure_unique_code(
                    uow,
                    company_id=company_id,
                    name=item["name"],
                ),
                name=item["name"],
                subject=item["subject"],
                message=item["message"],
                send_email=item["send_email"],
                send_whatsapp=item["send_whatsapp"],
                is_active=item["is_active"],
            )
            uow.settings.save_template(row)
        uow.session.flush()

    @staticmethod
    def get_company(uow, *, company_id: uuid.UUID):
        row = uow.settings.get_by_id(company_id=company_id)
        if row is None:
            raise NotFound("Company not found")
        return row

    @staticmethod
    def update_company(
        uow,
        *,
        company_id: uuid.UUID,
        name: str,
    ):
        row = SettingsAdminService.get_company(uow, company_id=company_id)
        row.name = name.strip()
        uow.settings.save(row)
        return row

    @staticmethod
    def get_integrations() -> dict:
        smtp_configured = bool(settings.SMTP_HOST and settings.SMTP_FROM)
        twilio_configured = bool(
            settings.TWILIO_ACCOUNT_SID
            and settings.TWILIO_AUTH_TOKEN
            and settings.TWILIO_WHATSAPP_FROM
        )
        storage_configured = bool(
            settings.MINIO_ENDPOINT
            and settings.MINIO_ACCESS_KEY
            and settings.MINIO_SECRET_KEY
            and settings.MINIO_BUCKET
        )
        return {
            "public_base_url": settings.PUBLIC_BASE_URL,
            "smtp_configured": smtp_configured,
            "email_enabled": settings.EMAIL_ENABLED,
            "twilio_configured": twilio_configured,
            "whatsapp_enabled": settings.WHATSAPP_ENABLED,
            "whatsapp_fallback_to_email": settings.WHATSAPP_FALLBACK_TO_EMAIL,
            "storage_configured": storage_configured,
            "waze_base_url": settings.WAZE_BASE_URL,
            "waze_navigation_enabled": settings.WAZE_NAVIGATION_ENABLED,
            "file_token_ttl_sec": settings.FILE_TOKEN_TTL_SEC,
            "file_token_uses": settings.FILE_TOKEN_USES,
            "journal_public_token_ttl_sec": settings.JOURNAL_PUBLIC_TOKEN_TTL_SEC,
            "sync_warn_lag": settings.SYNC_WARN_LAG,
            "sync_danger_lag": settings.SYNC_DANGER_LAG,
            "sync_warn_days_offline": settings.SYNC_WARN_DAYS_OFFLINE,
            "sync_danger_days_offline": settings.SYNC_DANGER_DAYS_OFFLINE,
            "sync_project_auto_problem_enabled": settings.SYNC_PROJECT_AUTO_PROBLEM_ENABLED,
            "sync_project_auto_problem_days": settings.SYNC_PROJECT_AUTO_PROBLEM_DAYS,
            "auth_login_rl_window_sec": settings.AUTH_LOGIN_RL_WINDOW_SEC,
            "auth_login_rl_max_req": settings.AUTH_LOGIN_RL_MAX_REQ,
            "auth_refresh_rl_window_sec": settings.AUTH_REFRESH_RL_WINDOW_SEC,
            "auth_refresh_rl_max_req": settings.AUTH_REFRESH_RL_MAX_REQ,
        }

    @staticmethod
    def get_integrations_health() -> dict:
        smtp_configured = bool(settings.SMTP_HOST and settings.SMTP_FROM)
        twilio_configured = bool(
            settings.TWILIO_ACCOUNT_SID
            and settings.TWILIO_AUTH_TOKEN
            and settings.TWILIO_WHATSAPP_FROM
        )
        email_notes: list[str] = []
        whatsapp_notes: list[str] = []

        if not smtp_configured:
            email_notes.append("SMTP host/from is not fully configured")
        if not settings.EMAIL_ENABLED:
            email_notes.append("Email channel is disabled")

        if not twilio_configured:
            whatsapp_notes.append("Twilio credentials/from number are not fully configured")
        if not settings.WHATSAPP_ENABLED:
            whatsapp_notes.append("WhatsApp channel is disabled")
        if not settings.TWILIO_STATUS_CALLBACK_URL:
            whatsapp_notes.append("Twilio status callback URL is not configured")

        return {
            "email": {
                "channel": "EMAIL",
                "provider": "SMTP",
                "enabled": settings.EMAIL_ENABLED,
                "configured": smtp_configured,
                "ready": bool(settings.EMAIL_ENABLED and smtp_configured),
                "callback_configured": False,
                "sender_identity": settings.SMTP_FROM,
                "fallback_enabled": None,
                "validation_enabled": None,
                "notes": email_notes,
            },
            "whatsapp": {
                "channel": "WHATSAPP",
                "provider": "TWILIO",
                "enabled": settings.WHATSAPP_ENABLED,
                "configured": twilio_configured,
                "ready": bool(settings.WHATSAPP_ENABLED and twilio_configured),
                "callback_configured": bool(settings.TWILIO_STATUS_CALLBACK_URL),
                "sender_identity": settings.TWILIO_WHATSAPP_FROM or None,
                "fallback_enabled": settings.WHATSAPP_FALLBACK_TO_EMAIL,
                "validation_enabled": settings.TWILIO_WEBHOOK_VALIDATE,
                "notes": whatsapp_notes,
            },
        }

    @staticmethod
    def send_test_email(
        *,
        to_email: str,
        subject: str | None,
        message: str | None,
    ) -> None:
        health = SettingsAdminService.get_integrations_health()["email"]
        if not health["ready"]:
            raise ValidationError("Email provider is not ready for test send")
        sender = SmtpEmailSender()
        sender.send(
            to_email=to_email,
            subject=(subject or "DIMAX test email").strip() or "DIMAX test email",
            body_text=(
                (message or "").strip()
                or "DIMAX Operations Suite test email"
            ),
            attachment_path=None,
            attachment_name=None,
        )

    @staticmethod
    def send_test_whatsapp(
        *,
        to_phone: str,
        message: str | None,
    ) -> str:
        health = SettingsAdminService.get_integrations_health()["whatsapp"]
        if not health["ready"]:
            raise ValidationError("WhatsApp provider is not ready for test send")
        sender = TwilioWhatsAppSender()
        callback = settings.TWILIO_STATUS_CALLBACK_URL or None
        return sender.send(
            to_phone_e164=to_phone,
            body_text=(
                (message or "").strip()
                or "DIMAX Operations Suite test WhatsApp message"
            ),
            media_url=None,
            status_callback_url=callback,
        )

    @staticmethod
    def list_templates(uow, *, company_id: uuid.UUID) -> list[CommunicationTemplateORM]:
        SettingsAdminService._ensure_default_templates(
            uow,
            company_id=company_id,
        )
        return uow.settings.list_templates(company_id=company_id)

    @staticmethod
    def get_template(
        uow,
        *,
        company_id: uuid.UUID,
        template_id: uuid.UUID,
    ) -> CommunicationTemplateORM:
        row = uow.settings.get_template(
            company_id=company_id,
            template_id=template_id,
        )
        if row is None:
            raise NotFound("Communication template not found")
        return row

    @staticmethod
    def _slugify_name(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
        return slug or "template"

    @staticmethod
    def _ensure_unique_code(
        uow,
        *,
        company_id: uuid.UUID,
        name: str,
        exclude_template_id: uuid.UUID | None = None,
    ) -> str:
        base = SettingsAdminService._slugify_name(name)
        candidate = base
        counter = 2
        while True:
            existing = uow.settings.get_template_by_code(
                company_id=company_id,
                code=candidate,
            )
            if existing is None or existing.id == exclude_template_id:
                return candidate
            candidate = f"{base}-{counter}"
            counter += 1

    @staticmethod
    def create_template(
        uow,
        *,
        company_id: uuid.UUID,
        name: str,
        subject: str,
        message: str,
        send_email: bool,
        send_whatsapp: bool,
        is_active: bool,
    ) -> CommunicationTemplateORM:
        if not send_email and not send_whatsapp:
            raise ValidationError("At least one delivery channel must be enabled")
        row = CommunicationTemplateORM(
            company_id=company_id,
            code=SettingsAdminService._ensure_unique_code(
                uow,
                company_id=company_id,
                name=name,
            ),
            name=name.strip(),
            subject=subject.strip(),
            message=message.strip(),
            send_email=send_email,
            send_whatsapp=send_whatsapp,
            is_active=is_active,
        )
        uow.settings.save_template(row)
        return row

    @staticmethod
    def update_template(
        uow,
        *,
        company_id: uuid.UUID,
        template_id: uuid.UUID,
        name: str | None,
        subject: str | None,
        message: str | None,
        send_email: bool | None,
        send_whatsapp: bool | None,
        is_active: bool | None,
    ) -> CommunicationTemplateORM:
        row = SettingsAdminService.get_template(
            uow,
            company_id=company_id,
            template_id=template_id,
        )
        if name is not None:
            row.name = name.strip()
            row.code = SettingsAdminService._ensure_unique_code(
                uow,
                company_id=company_id,
                name=row.name,
                exclude_template_id=row.id,
            )
        if subject is not None:
            row.subject = subject.strip()
        if message is not None:
            row.message = message.strip()
        if send_email is not None:
            row.send_email = send_email
        if send_whatsapp is not None:
            row.send_whatsapp = send_whatsapp
        if is_active is not None:
            row.is_active = is_active
        if not row.send_email and not row.send_whatsapp:
            raise ValidationError("At least one delivery channel must be enabled")
        uow.settings.save_template(row)
        return row

    @staticmethod
    def delete_template(
        uow,
        *,
        company_id: uuid.UUID,
        template_id: uuid.UUID,
    ) -> None:
        row = SettingsAdminService.get_template(
            uow,
            company_id=company_id,
            template_id=template_id,
        )
        uow.settings.delete_template(row)

    @staticmethod
    def _render_text(text: str, variables: dict[str, str | None]) -> str:
        rendered = text
        for key, value in variables.items():
            rendered = rendered.replace(
                "{{" + key + "}}",
                value or "",
            )
        return rendered

    @staticmethod
    def build_template_variables(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID | None,
    ) -> dict[str, str | None]:
        variables = {
            "company_name": None,
            "project_name": None,
            "project_address": None,
            "journal_title": None,
            "public_url": None,
        }
        company = SettingsAdminService.get_company(uow, company_id=company_id)
        variables["company_name"] = company.name

        if journal_id is None:
            return variables

        journal = uow.journals.get(company_id=company_id, journal_id=journal_id)
        if journal is None:
            raise NotFound("Journal not found")
        project = uow.projects.get(
            company_id=company_id,
            project_id=journal.project_id,
        )
        variables["journal_title"] = journal.title or f"Journal {journal.id}"
        if project is not None:
            variables["project_name"] = project.name
            variables["project_address"] = project.address
        if journal.public_token:
            variables["public_url"] = (
                f"{settings.PUBLIC_BASE_URL}/api/v1/public/journals/"
                f"{journal.public_token}"
            )
        return variables

    @staticmethod
    def render_template_preview(
        uow,
        *,
        company_id: uuid.UUID,
        template_id: uuid.UUID,
        journal_id: uuid.UUID | None,
    ) -> tuple[CommunicationTemplateORM, dict[str, str | None], str, str]:
        template = SettingsAdminService.get_template(
            uow,
            company_id=company_id,
            template_id=template_id,
        )
        variables = SettingsAdminService.build_template_variables(
            uow,
            company_id=company_id,
            journal_id=journal_id,
        )
        return (
            template,
            variables,
            SettingsAdminService._render_text(template.subject, variables),
            SettingsAdminService._render_text(template.message, variables),
        )
