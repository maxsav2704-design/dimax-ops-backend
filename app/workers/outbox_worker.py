from __future__ import annotations

import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.integrations.email.smtp_sender import SmtpEmailSender
from app.integrations.storage.storage_service import StorageService
from app.integrations.whatsapp.twilio_sender import TwilioWhatsAppSender
from app.modules.journal.domain.enums import JournalDeliveryStatus
from app.modules.journal.infrastructure.repositories import JournalRepository
from app.modules.outbox.domain.enums import OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.outbox.infrastructure.repositories import OutboxRepository
from app.shared.infrastructure.db.session import SessionLocal


email_sender = SmtpEmailSender()
wa_sender = TwilioWhatsAppSender()


def _enqueue_whatsapp_fallback_email(
    repo: OutboxRepository,
    msg,
    *,
    payload: dict,
    error: str,
) -> bool:
    if not settings.WHATSAPP_FALLBACK_TO_EMAIL:
        return False

    fallback_email = payload.get("fallback_email")
    object_key = payload.get("object_key")
    if not fallback_email or not object_key:
        return False

    fallback = OutboxMessageORM(
        company_id=msg.company_id,
        channel=OutboxChannel.EMAIL,
        status=OutboxStatus.PENDING,
        correlation_id=msg.correlation_id,
        payload={
            "to_email": fallback_email,
            "subject": payload.get("fallback_subject") or "Journal delivery",
            "body_text": (
                payload.get("fallback_body_text")
                or "WhatsApp delivery failed; PDF sent by email."
            ),
            "object_key": object_key,
            "attachment_name": payload.get("attachment_name"),
            "fallback_reason": error[:500],
        },
        attempts=0,
        max_attempts=5,
        scheduled_at=datetime.now(timezone.utc),
    )
    repo.enqueue(fallback)
    return True


def run_once(limit: int = 20) -> int:
    session = SessionLocal()
    try:
        repo = OutboxRepository(session)
        msgs = repo.lock_next_batch(company_id=None, limit=limit)

        processed = 0
        for m in msgs:
            try:
                payload = m.payload

                if m.channel == OutboxChannel.EMAIL:
                    attachment_path = None
                    object_key = payload.get("object_key")
                    if object_key:
                        pdf_bytes = StorageService.get_pdf(object_key=object_key)
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".pdf"
                        ) as f:
                            f.write(pdf_bytes)
                            attachment_path = f.name
                    try:
                        email_sender.send(
                            to_email=payload["to_email"],
                            subject=payload["subject"],
                            body_text=payload["body_text"],
                            attachment_path=attachment_path,
                            attachment_name=payload.get("attachment_name"),
                        )
                    finally:
                        if attachment_path and Path(attachment_path).exists():
                            Path(attachment_path).unlink(missing_ok=True)
                    if m.correlation_id:
                        jr = JournalRepository(session)
                        jr.set_email_status(
                            company_id=m.company_id,
                            journal_id=m.correlation_id,
                            status=JournalDeliveryStatus.DELIVERED,
                            sent_at=datetime.now(timezone.utc),
                            error=None,
                        )
                elif m.channel == OutboxChannel.WHATSAPP:
                    callback = None
                    if settings.TWILIO_STATUS_CALLBACK_URL:
                        callback = (
                            f"{settings.TWILIO_STATUS_CALLBACK_URL}"
                            f"?outbox_id={m.id}"
                        )
                    sid = wa_sender.send(
                        to_phone_e164=payload["to_phone"],
                        body_text=payload["body_text"],
                        media_url=payload.get("media_url"),
                        status_callback_url=callback,
                    )
                    repo.set_provider_status(
                        m,
                        provider_message_id=sid,
                        provider_status="created",
                        provider_error=None,
                    )
                    if m.correlation_id:
                        jr = JournalRepository(session)
                        jr.set_whatsapp_status(
                            company_id=m.company_id,
                            journal_id=m.correlation_id,
                            status=JournalDeliveryStatus.PENDING,
                            sent_at=datetime.now(timezone.utc),
                            delivered_at=None,
                            error=None,
                        )
                else:
                    raise RuntimeError(f"Unknown channel: {m.channel}")

                repo.mark_sent(m)
                processed += 1

            except Exception as e:
                err = str(e)
                payload = m.payload if isinstance(m.payload, dict) else {}
                fallback_email_enqueued = False
                if m.channel == OutboxChannel.WHATSAPP:
                    fallback_email_enqueued = _enqueue_whatsapp_fallback_email(
                        repo,
                        m,
                        payload=payload,
                        error=err,
                    )

                repo.mark_failed(m, error=err)
                if m.correlation_id:
                    jr = JournalRepository(session)
                    if m.channel == OutboxChannel.EMAIL:
                        jr.set_email_status(
                            company_id=m.company_id,
                            journal_id=m.correlation_id,
                            status=JournalDeliveryStatus.FAILED,
                            error=err,
                        )
                    elif m.channel == OutboxChannel.WHATSAPP:
                        if fallback_email_enqueued:
                            jr.set_email_status(
                                company_id=m.company_id,
                                journal_id=m.correlation_id,
                                status=JournalDeliveryStatus.PENDING,
                                sent_at=None,
                                error=None,
                            )
                        jr.set_whatsapp_status(
                            company_id=m.company_id,
                            journal_id=m.correlation_id,
                            status=JournalDeliveryStatus.FAILED,
                            error=err,
                        )

        session.commit()
        return processed

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    while True:
        processed = run_once(limit=20)
        time.sleep(1 if processed > 0 else 3)


if __name__ == "__main__":
    main()
