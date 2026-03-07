from __future__ import annotations

import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from app.core.config import settings
from app.shared.domain.errors import NotFound, ValidationError
from app.modules.journal.application.use_cases import JournalUseCases
from app.modules.outbox.domain.enums import OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.files.application.service import FileTokenService
from app.modules.journal.domain.enums import JournalDeliveryStatus
from app.modules.settings.application.admin_service import SettingsAdminService


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _compose_email_body(message: str, public_url: str | None) -> str:
    parts = []
    if message:
        parts.append(message)
    parts.append("Attached: journal PDF.")
    if public_url:
        parts.append(f"Public link: {public_url}")
    return "\n\n".join(parts)


def _compose_whatsapp_body(message: str, public_url: str | None) -> str:
    parts = []
    if message:
        parts.append(message)
    if public_url:
        parts.append(f"Journal link: {public_url}")
    return "\n".join(parts) if parts else "Journal"


class JournalSendService:
    @staticmethod
    def enqueue_send(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
        template_id: uuid.UUID | None,
        email_to: str | None,
        whatsapp_to: str | None,
        subject: str | None,
        message: str | None,
        send_email: bool,
        send_whatsapp: bool,
    ) -> dict:
        if not send_email and not send_whatsapp:
            raise ValidationError("At least one channel must be enabled")
        if send_email and not settings.EMAIL_ENABLED:
            raise ValidationError("Email channel is disabled")
        if send_whatsapp and not settings.WHATSAPP_ENABLED:
            raise ValidationError("WhatsApp channel is disabled")

        j = uow.journals.get(company_id=company_id, journal_id=journal_id)
        if not j:
            raise NotFound("Journal not found")

        pdf_file = JournalUseCases.export_pdf(
            uow,
            company_id=company_id,
            journal_id=journal_id,
        )

        public_url = None
        if j.public_token:
            public_url = (
                f"{settings.PUBLIC_BASE_URL}/api/v1/public/journals/"
                f"{j.public_token}"
            )

        subject_final = (subject or "").strip()
        message_final = (message or "").strip()
        template_meta = {
            "template_id": None,
            "template_code": None,
            "template_name": None,
        }
        if template_id is not None:
            template_row, _, rendered_subject, rendered_message = (
                SettingsAdminService.render_template_preview(
                    uow,
                    company_id=company_id,
                    template_id=template_id,
                    journal_id=journal_id,
                )
            )
            template_meta = {
                "template_id": str(template_row.id),
                "template_code": template_row.code,
                "template_name": template_row.name,
            }
            if not subject_final:
                subject_final = rendered_subject.strip()
            if not message_final:
                message_final = rendered_message.strip()
        if not subject_final:
            subject_final = j.title or f"Journal {journal_id}"

        enqueued = {"email": False, "whatsapp": False}
        outbox_ids = {"email": None, "whatsapp": None}

        if send_email:
            if not email_to:
                raise ValidationError("email_to is required for email send")
            msg = OutboxMessageORM(
                company_id=company_id,
                channel=OutboxChannel.EMAIL,
                status=OutboxStatus.PENDING,
                correlation_id=journal_id,
                payload={
                    "to_email": email_to,
                    "subject": subject_final,
                    "body_text": _compose_email_body(
                        message_final, public_url
                    ),
                    **template_meta,
                    "object_key": pdf_file.file_path,
                    "attachment_name": f"journal_{journal_id}.pdf",
                },
                attempts=0,
                max_attempts=5,
                scheduled_at=utcnow(),
            )
            uow.outbox.enqueue(msg)
            outbox_ids["email"] = str(msg.id)
            enqueued["email"] = True
            uow.journals.set_email_status(
                company_id=company_id,
                journal_id=journal_id,
                status=JournalDeliveryStatus.PENDING,
                sent_at=None,
                error=None,
            )

        if send_whatsapp:
            if not whatsapp_to:
                raise ValidationError(
                    "whatsapp_to is required for whatsapp send"
                )
            token = FileTokenService.create_token_for_object(
                uow,
                company_id=company_id,
                bucket=pdf_file.bucket,
                object_key=pdf_file.file_path,
                mime_type=pdf_file.mime_type,
                file_name=f"journal_{journal_id}.pdf",
                ttl_sec=3600,
                uses=2,
                audience=whatsapp_to,
            )
            media_url = (
                f"{settings.PUBLIC_BASE_URL}/api/v1/public/files/{token}"
                f"?aud={quote(whatsapp_to, safe='')}"
            )
            wa_text = _compose_whatsapp_body(message_final, public_url)
            fallback_email = (
                email_to.strip()
                if (email_to and not send_email)
                else None
            )
            msg = OutboxMessageORM(
                company_id=company_id,
                channel=OutboxChannel.WHATSAPP,
                status=OutboxStatus.PENDING,
                correlation_id=journal_id,
                payload={
                    "to_phone": whatsapp_to,
                    "body_text": wa_text,
                    "media_url": media_url,
                    **template_meta,
                    "object_key": pdf_file.file_path,
                    "attachment_name": f"journal_{journal_id}.pdf",
                    "fallback_email": fallback_email,
                    "fallback_subject": subject_final,
                    "fallback_body_text": _compose_email_body(
                        message_final, public_url
                    ),
                },
                attempts=0,
                max_attempts=5,
                scheduled_at=utcnow(),
            )
            uow.outbox.enqueue(msg)
            outbox_ids["whatsapp"] = str(msg.id)
            enqueued["whatsapp"] = True
            uow.journals.set_whatsapp_status(
                company_id=company_id,
                journal_id=journal_id,
                status=JournalDeliveryStatus.PENDING,
                sent_at=None,
                delivered_at=None,
                error=None,
            )

        return {
            "ok": True,
            "enqueued": enqueued,
            "outbox_ids": outbox_ids,
            "public_url": public_url,
            "object_key": pdf_file.file_path,
        }
