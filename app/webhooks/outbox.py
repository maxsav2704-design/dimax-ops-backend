from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.v1.deps import get_uow
from app.core.config import settings
from app.shared.infrastructure.observability import get_logger, log_event
from app.shared.domain.errors import Forbidden
from app.webhooks.delivery_service import OutboxDeliveryWebhookService


class OutboxDeliveryStatusWebhookBody(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    channel: str | None = Field(default=None, max_length=40)
    outbox_id: UUID | None = None
    provider_message_id: str | None = Field(default=None, max_length=120)
    event_id: str | None = Field(default=None, max_length=160)
    event_type: str = Field(default="delivery_status", max_length=60)
    status: str = Field(min_length=1, max_length=60)
    error: str | None = Field(default=None, max_length=5000)
    delivered_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


logger = get_logger(__name__)


def _validate_outbox_webhook_token(request: Request) -> None:
    token = (settings.OUTBOX_WEBHOOK_TOKEN or "").strip()
    if not token:
        return
    provided = (request.headers.get("X-Webhook-Token") or "").strip()
    if provided != token:
        log_event(
            logger,
            "webhook.outbox.forbidden",
            level="warning",
            reason="invalid_token",
            path=str(request.url.path),
            client_ip=request.client.host if request.client else None,
        )
        raise Forbidden("Invalid outbox webhook token")


router = APIRouter(prefix="/webhooks/outbox", tags=["Webhooks / Outbox"])


@router.post("/status", response_class=PlainTextResponse)
async def delivery_status_webhook(
    body: OutboxDeliveryStatusWebhookBody,
    request: Request,
    uow=Depends(get_uow),
):
    _validate_outbox_webhook_token(request)
    external_event_id = body.event_id
    if not external_event_id:
        suffix = body.status.strip().lower()
        if body.provider_message_id:
            external_event_id = f"{body.provider_message_id}:{suffix}"
        elif body.outbox_id:
            external_event_id = f"{body.outbox_id}:{suffix}"

    payload = dict(body.payload or {})
    payload.update(
        {
            "provider": body.provider,
            "channel": body.channel,
            "status": body.status,
            "error": body.error,
            "provider_message_id": body.provider_message_id,
            "outbox_id": str(body.outbox_id) if body.outbox_id else None,
        }
    )

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    with uow:
        result = OutboxDeliveryWebhookService.process(
            uow,
            provider=body.provider.strip().lower(),
            channel=body.channel.strip().upper() if body.channel else None,
            event_type=body.event_type.strip().lower() or "delivery_status",
            external_event_id=external_event_id,
            payload=payload,
            outbox_id=body.outbox_id,
            provider_message_id=body.provider_message_id,
            provider_status=body.status,
            provider_error=body.error,
            delivered_at=body.delivered_at,
            ip=ip,
            user_agent=user_agent,
        )
    log_event(
        logger,
        "webhook.outbox.processed",
        provider=body.provider.strip().lower(),
        channel=body.channel.strip().upper() if body.channel else None,
        event_type=body.event_type.strip().lower() or "delivery_status",
        status=body.status,
        external_event_id=external_event_id,
        provider_message_id=body.provider_message_id,
        outbox_id=result.get("outbox_id"),
        updated=result.get("updated"),
        duplicate=result.get("duplicate"),
        reason=result.get("reason"),
        client_ip=ip,
    )
    return "ok"
