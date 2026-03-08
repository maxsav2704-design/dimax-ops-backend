from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from app.api.v1.deps import get_uow
from app.core.config import settings
from app.shared.infrastructure.observability import get_logger, log_event
from app.shared.domain.errors import Forbidden
from app.webhooks.delivery_service import OutboxDeliveryWebhookService


logger = get_logger(__name__)


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
        log_event(
            logger,
            "webhook.twilio.forbidden",
            level="warning",
            reason="invalid_signature",
            path=str(request.url.path),
            client_ip=request.client.host if request.client else None,
        )
        raise Forbidden("Invalid Twilio signature")


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
    event_id = (
        f"{message_sid or 'unknown'}:"
        f"{(message_status or 'unknown').lower()}:"
        f"{(error_code or '').strip()}:"
        f"{(error_message or '').strip()}"
    )[:160]
    error_text = f"{error_code or ''} {error_message or ''}".strip() or None

    with uow:
        result = OutboxDeliveryWebhookService.process(
            uow,
            provider="twilio",
            channel="WHATSAPP",
            event_type="message_status",
            external_event_id=event_id,
            payload=dict(form),
            outbox_id=outbox_id,
            provider_message_id=message_sid,
            provider_status=message_status,
            provider_error=error_text,
            delivered_at=None,
            ip=ip,
            user_agent=ua,
        )
    log_event(
        logger,
        "webhook.twilio.processed",
        provider="twilio",
        channel="WHATSAPP",
        event_type="message_status",
        status=message_status,
        external_event_id=event_id,
        provider_message_id=message_sid,
        outbox_id=result.get("outbox_id"),
        updated=result.get("updated"),
        duplicate=result.get("duplicate"),
        reason=result.get("reason"),
        client_ip=ip,
    )

    return "ok"
