from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from app.api.v1.deps import get_uow
from app.core.config import settings
from app.modules.journal.domain.enums import JournalDeliveryStatus
from app.modules.journal.infrastructure.repositories import JournalRepository
from app.modules.outbox.domain.enums import DeliveryStatus
from app.shared.domain.errors import Forbidden
from app.webhooks.models import WebhookEventORM


def _validate_twilio_signature(request: Request, form: dict) -> None:
    if not settings.TWILIO_WEBHOOK_VALIDATE:
        return
    try:
        from twilio.request_validator import RequestValidator
    except Exception as e:
        raise Forbidden("Twilio validator not installed") from e

    sig = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    token = settings.TWILIO_WEBHOOK_AUTH_TOKEN or settings.TWILIO_AUTH_TOKEN
    v = RequestValidator(token)
    ok = v.validate(url, form, sig)
    if not ok:
        raise Forbidden("Invalid Twilio signature")


def _outbox_model():
    from app.modules.outbox.infrastructure.models import OutboxMessageORM

    return OutboxMessageORM


router = APIRouter(prefix="/webhooks/twilio", tags=["Webhooks / Twilio"])


@router.post("/status", response_class=PlainTextResponse)
async def status_callback(
    request: Request,
    outbox_id: UUID = Query(...),
    uow=Depends(get_uow),
):
    form = dict(await request.form())
    _validate_twilio_signature(request, form)

    message_sid = form.get("MessageSid") or form.get("SmsSid")
    message_status = form.get("MessageStatus") or form.get("SmsStatus")
    error_code = form.get("ErrorCode")
    error_message = form.get("ErrorMessage")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    with uow:
        uow.session.add(
            WebhookEventORM(
                company_id=None,
                provider="twilio",
                event_type="message_status",
                external_id=form.get("MessageSid") or form.get("SmsSid"),
                payload=dict(form),
                ip=ip,
                user_agent=ua,
            )
        )

        OutboxMessageORM = _outbox_model()
        msg = (
            uow.outbox.session.query(OutboxMessageORM)
            .filter(OutboxMessageORM.id == outbox_id)
            .one_or_none()
        )
        if not msg:
            return "ok"

        if message_sid and not msg.provider_message_id:
            msg.provider_message_id = message_sid

        if message_status:
            msg.provider_status = str(message_status)
            s = str(message_status).lower()
            if s == "delivered":
                msg.delivery_status = DeliveryStatus.DELIVERED
                msg.delivered_at = msg.delivered_at or datetime.now(
                    timezone.utc
                )
            elif s in ("failed", "undelivered"):
                if msg.delivery_status != DeliveryStatus.DELIVERED:
                    msg.delivery_status = DeliveryStatus.FAILED
            else:
                if msg.delivery_status not in (
                    DeliveryStatus.DELIVERED,
                    DeliveryStatus.FAILED,
                ):
                    msg.delivery_status = DeliveryStatus.PENDING

        if error_code or error_message:
            msg.provider_error = (
                f"{error_code or ''} {error_message or ''}".strip()
            )
            if msg.delivery_status != DeliveryStatus.DELIVERED:
                msg.delivery_status = DeliveryStatus.FAILED

        uow.outbox.session.add(msg)

        if msg.correlation_id and str(msg.channel) == "WHATSAPP":
            jr = JournalRepository(uow.outbox.session)
            s = (message_status or "").lower()
            if s == "delivered":
                jr.set_whatsapp_status(
                    company_id=msg.company_id,
                    journal_id=msg.correlation_id,
                    status=JournalDeliveryStatus.DELIVERED,
                    delivered_at=datetime.now(timezone.utc),
                    error=None,
                )
            elif s in ("failed", "undelivered"):
                jr.set_whatsapp_status(
                    company_id=msg.company_id,
                    journal_id=msg.correlation_id,
                    status=JournalDeliveryStatus.FAILED,
                    error=msg.provider_error or "Twilio delivery failed",
                )

    return "ok"
