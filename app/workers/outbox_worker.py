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
from app.modules.outbox.domain.enums import OutboxChannel
from app.modules.outbox.infrastructure.repositories import OutboxRepository
from app.shared.infrastructure.db.session import SessionLocal


email_sender = SmtpEmailSender()
wa_sender = TwilioWhatsAppSender()


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
                repo.mark_failed(m, error=str(e))
                if m.correlation_id:
                    jr = JournalRepository(session)
                    err = str(e)
                    if m.channel == OutboxChannel.EMAIL:
                        jr.set_email_status(
                            company_id=m.company_id,
                            journal_id=m.correlation_id,
                            status=JournalDeliveryStatus.FAILED,
                            error=err,
                        )
                    elif m.channel == OutboxChannel.WHATSAPP:
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
