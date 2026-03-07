from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.modules.audit.application.service import AuditService
from app.modules.journal.domain.enums import JournalDeliveryStatus
from app.modules.outbox.domain.enums import DeliveryStatus, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.webhooks.models import WebhookEventORM

SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")

_DELIVERED_STATUSES = {
    "delivered",
    "delivery",
    "success",
    "completed",
    "confirmed",
}
_FAILED_STATUSES = {
    "failed",
    "undelivered",
    "bounced",
    "bounce",
    "dropped",
    "blocked",
    "rejected",
    "complained",
    "error",
}


def _status_to_delivery_status(raw_status: str | None) -> DeliveryStatus:
    value = (raw_status or "").strip().lower()
    if value in _DELIVERED_STATUSES:
        return DeliveryStatus.DELIVERED
    if value in _FAILED_STATUSES:
        return DeliveryStatus.FAILED
    return DeliveryStatus.PENDING


def _serialize_outbox(msg: OutboxMessageORM) -> dict[str, Any]:
    return {
        "status": str(msg.status.value if hasattr(msg.status, "value") else msg.status),
        "delivery_status": str(
            msg.delivery_status.value
            if hasattr(msg.delivery_status, "value")
            else msg.delivery_status
        ),
        "provider_message_id": msg.provider_message_id,
        "provider_status": msg.provider_status,
        "provider_error": msg.provider_error,
        "delivered_at": msg.delivered_at.isoformat() if msg.delivered_at else None,
        "last_error": msg.last_error,
    }


class OutboxDeliveryWebhookService:
    @staticmethod
    def process(
        uow,
        *,
        provider: str,
        channel: str | None,
        event_type: str,
        external_event_id: str | None,
        payload: dict[str, Any],
        outbox_id: uuid.UUID | None = None,
        provider_message_id: str | None = None,
        provider_status: str | None = None,
        provider_error: str | None = None,
        delivered_at: datetime | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        message = OutboxDeliveryWebhookService._resolve_message(
            uow,
            outbox_id=outbox_id,
            provider_message_id=provider_message_id,
        )
        company_id = message.company_id if message else None

        if OutboxDeliveryWebhookService._is_duplicate_event(
            uow,
            provider=provider,
            event_type=event_type,
            external_event_id=external_event_id,
            company_id=company_id,
        ):
            return {
                "updated": False,
                "duplicate": True,
                "outbox_id": str(message.id) if message else None,
            }

        uow.session.add(
            WebhookEventORM(
                company_id=company_id,
                provider=provider,
                event_type=event_type,
                external_id=external_event_id,
                payload=payload,
                ip=ip,
                user_agent=user_agent,
            )
        )

        if message is None:
            return {"updated": False, "duplicate": False, "outbox_id": None}

        if channel:
            message_channel = str(
                message.channel.value if hasattr(message.channel, "value") else message.channel
            )
            if message_channel.upper() != channel.upper():
                return {
                    "updated": False,
                    "duplicate": False,
                    "outbox_id": str(message.id),
                }

        before = _serialize_outbox(message)
        now = datetime.now(timezone.utc)
        status = _status_to_delivery_status(provider_status)
        target_delivered_at = delivered_at
        if status == DeliveryStatus.DELIVERED and target_delivered_at is None:
            target_delivered_at = now

        if provider_message_id and not message.provider_message_id:
            message.provider_message_id = provider_message_id
        if provider_status:
            message.provider_status = provider_status[:40]
        if provider_error:
            trimmed_error = provider_error[:5000]
            message.provider_error = trimmed_error
            message.last_error = trimmed_error

        if status == DeliveryStatus.DELIVERED:
            message.delivery_status = DeliveryStatus.DELIVERED
            message.delivered_at = target_delivered_at
            message.status = OutboxStatus.SENT
            message.last_error = None
        elif status == DeliveryStatus.FAILED:
            if message.delivery_status != DeliveryStatus.DELIVERED:
                message.delivery_status = DeliveryStatus.FAILED
            message.status = OutboxStatus.FAILED
        else:
            if message.delivery_status not in (
                DeliveryStatus.DELIVERED,
                DeliveryStatus.FAILED,
            ):
                message.delivery_status = DeliveryStatus.PENDING

        uow.outbox.session.add(message)
        OutboxDeliveryWebhookService._sync_journal_delivery(
            uow,
            message=message,
            error=provider_error,
            delivered_at=target_delivered_at,
            now=now,
        )
        uow.session.flush()
        OutboxDeliveryWebhookService._handle_delivery_risk_issue(
            uow,
            message=message,
            provider=provider,
            provider_status=provider_status,
            provider_error=provider_error,
        )

        after = _serialize_outbox(message)
        AuditService.add(
            uow,
            company_id=message.company_id,
            actor_user_id=SYSTEM_ACTOR_ID,
            entity_type="outbox_message",
            entity_id=message.id,
            action="OUTBOX_DELIVERY_STATUS_WEBHOOK",
            reason=f"{provider}:{event_type}",
            before=before,
            after=after,
        )

        return {"updated": True, "duplicate": False, "outbox_id": str(message.id)}

    @staticmethod
    def _resolve_message(
        uow,
        *,
        outbox_id: uuid.UUID | None,
        provider_message_id: str | None,
    ) -> OutboxMessageORM | None:
        if outbox_id is not None:
            return (
                uow.outbox.session.query(OutboxMessageORM)
                .filter(OutboxMessageORM.id == outbox_id)
                .one_or_none()
            )
        if provider_message_id:
            return uow.outbox.get_by_provider_message_id(provider_message_id)
        return None

    @staticmethod
    def _is_duplicate_event(
        uow,
        *,
        provider: str,
        event_type: str,
        external_event_id: str | None,
        company_id: uuid.UUID | None,
    ) -> bool:
        if not external_event_id:
            return False
        q = uow.session.query(WebhookEventORM.id).filter(
            WebhookEventORM.provider == provider,
            WebhookEventORM.event_type == event_type,
            WebhookEventORM.external_id == external_event_id,
        )
        if company_id is None:
            q = q.filter(WebhookEventORM.company_id.is_(None))
        else:
            q = q.filter(WebhookEventORM.company_id == company_id)
        return q.first() is not None

    @staticmethod
    def _sync_journal_delivery(
        uow,
        *,
        message: OutboxMessageORM,
        error: str | None,
        delivered_at: datetime | None,
        now: datetime,
    ) -> None:
        if not message.correlation_id:
            return
        channel = str(message.channel.value if hasattr(message.channel, "value") else message.channel)
        journal_id = message.correlation_id
        if channel == "WHATSAPP":
            if message.delivery_status == DeliveryStatus.DELIVERED:
                uow.journals.set_whatsapp_status(
                    company_id=message.company_id,
                    journal_id=journal_id,
                    status=JournalDeliveryStatus.DELIVERED,
                    sent_at=message.sent_at or now,
                    delivered_at=delivered_at or now,
                    error=None,
                )
            elif message.delivery_status == DeliveryStatus.FAILED:
                uow.journals.set_whatsapp_status(
                    company_id=message.company_id,
                    journal_id=journal_id,
                    status=JournalDeliveryStatus.FAILED,
                    error=(error or message.provider_error or "Delivery failed")[:5000],
                )
            else:
                uow.journals.set_whatsapp_status(
                    company_id=message.company_id,
                    journal_id=journal_id,
                    status=JournalDeliveryStatus.PENDING,
                    sent_at=message.sent_at or now,
                    delivered_at=None,
                    error=None,
                )
            return

        if channel == "EMAIL":
            if message.delivery_status == DeliveryStatus.DELIVERED:
                uow.journals.set_email_status(
                    company_id=message.company_id,
                    journal_id=journal_id,
                    status=JournalDeliveryStatus.DELIVERED,
                    sent_at=message.sent_at or delivered_at or now,
                    error=None,
                )
            elif message.delivery_status == DeliveryStatus.FAILED:
                uow.journals.set_email_status(
                    company_id=message.company_id,
                    journal_id=journal_id,
                    status=JournalDeliveryStatus.FAILED,
                    error=(error or message.provider_error or "Delivery failed")[:5000],
                )
            else:
                uow.journals.set_email_status(
                    company_id=message.company_id,
                    journal_id=journal_id,
                    status=JournalDeliveryStatus.PENDING,
                    sent_at=message.sent_at or now,
                    error=None,
                )

    @staticmethod
    def _handle_delivery_risk_issue(
        uow,
        *,
        message: OutboxMessageORM,
        provider: str,
        provider_status: str | None,
        provider_error: str | None,
    ) -> None:
        if not settings.OUTBOX_DELIVERY_RISK_AUTO_ISSUE_ENABLED:
            return
        if not message.correlation_id:
            return

        journal = uow.journals.get(
            company_id=message.company_id,
            journal_id=message.correlation_id,
        )
        if not journal:
            return

        project_id = journal.project_id
        if message.delivery_status == DeliveryStatus.FAILED:
            failed_count = uow.outbox.count_failed_delivery_for_project(
                company_id=message.company_id,
                project_id=project_id,
                window_hours=settings.OUTBOX_DELIVERY_RISK_WINDOW_HOURS,
            )
            if failed_count < int(settings.OUTBOX_DELIVERY_RISK_MIN_FAILED):
                return

            details = (
                "Outbox delivery failures detected. "
                f"provider={provider}; status={provider_status or 'unknown'}; "
                f"failed_count={failed_count}; error={(provider_error or message.provider_error or '-')[:200]}"
            )
            issue_id, changed = uow.issues.upsert_delivery_outbox_risk(
                company_id=message.company_id,
                project_id=project_id,
                details=details,
            )
            if changed and issue_id is not None:
                AuditService.add(
                    uow,
                    company_id=message.company_id,
                    actor_user_id=SYSTEM_ACTOR_ID,
                    entity_type="issue",
                    entity_id=issue_id,
                    action="OUTBOX_DELIVERY_RISK_OPEN",
                    reason=details[:500],
                    before=None,
                    after={"status": "OPEN", "title": "DELIVERY_OUTBOX_RISK"},
                )
            return

        if message.delivery_status == DeliveryStatus.DELIVERED:
            failed_count = uow.outbox.count_failed_delivery_for_project(
                company_id=message.company_id,
                project_id=project_id,
                window_hours=settings.OUTBOX_DELIVERY_RISK_WINDOW_HOURS,
            )
            if failed_count > 0:
                return

            issue_id, changed = uow.issues.close_delivery_outbox_risk(
                company_id=message.company_id,
                project_id=project_id,
            )
            if changed and issue_id is not None:
                AuditService.add(
                    uow,
                    company_id=message.company_id,
                    actor_user_id=SYSTEM_ACTOR_ID,
                    entity_type="issue",
                    entity_id=issue_id,
                    action="OUTBOX_DELIVERY_RISK_CLOSE",
                    reason=f"Recovered after delivery via provider={provider}",
                    before={"status": "OPEN", "title": "DELIVERY_OUTBOX_RISK"},
                    after={"status": "CLOSED", "title": "DELIVERY_OUTBOX_RISK"},
                )
