from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import func

from app.modules.outbox.api.admin_schemas import (
    OutboxItemDTO,
    OutboxListResponse,
    OutboxSummaryResponse,
)
from app.modules.outbox.domain.enums import (
    DeliveryStatus,
    OutboxChannel,
    OutboxStatus,
)
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.shared.domain.errors import NotFound, ValidationError


def _enum_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    raw = str(value)
    return raw.split(".")[-1] if "." in raw else raw


def _parse_enum(enum_cls: type[Enum], raw: str, *, field: str):
    normalized = raw.strip().upper()
    for member in enum_cls:
        candidates = {
            member.name.upper(),
            str(member.value).upper(),
            str(member).upper(),
            str(member).split(".")[-1].upper(),
        }
        if normalized in candidates:
            return member
    allowed = ", ".join(str(member.value) for member in enum_cls)
    raise ValidationError(
        f"Unsupported {field}",
        details={"field": field, "allowed": allowed},
    )


def _to_dto(row: OutboxMessageORM) -> OutboxItemDTO:
    payload = row.payload if isinstance(row.payload, dict) else {}
    recipient = payload.get("to_email") or payload.get("to_phone")
    subject = payload.get("subject")
    template_id = payload.get("template_id")
    template_code = payload.get("template_code")
    template_name = payload.get("template_name")
    body_text = payload.get("body_text")
    message_preview = None
    if body_text is not None:
        message_preview = str(body_text).strip()[:180] or None
    attachment_name = payload.get("attachment_name")
    return OutboxItemDTO(
        id=row.id,
        correlation_id=row.correlation_id,
        channel=_enum_value(row.channel),
        recipient=str(recipient) if recipient else None,
        subject=str(subject) if subject else None,
        template_id=str(template_id) if template_id else None,
        template_code=str(template_code) if template_code else None,
        template_name=str(template_name) if template_name else None,
        message_preview=message_preview,
        attachment_name=str(attachment_name) if attachment_name else None,
        status=_enum_value(row.status),
        scheduled_at=row.scheduled_at,
        max_attempts=row.max_attempts,
        last_error=row.last_error,
        provider_message_id=row.provider_message_id,
        provider_status=row.provider_status,
        provider_error=row.provider_error,
        attempts=row.attempts,
        created_at=row.created_at,
        sent_at=row.sent_at,
        delivery_status=_enum_value(row.delivery_status),
        delivered_at=row.delivered_at,
    )


class OutboxAdminService:
    @staticmethod
    def list_outbox(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID | None,
        channel: str | None,
        status: str | None,
        delivery_status: str | None,
        limit: int,
    ) -> OutboxListResponse:
        q = uow.session.query(OutboxMessageORM).filter(
            OutboxMessageORM.company_id == company_id
        )
        if journal_id is not None:
            q = q.filter(OutboxMessageORM.correlation_id == journal_id)
        if channel:
            q = q.filter(
                OutboxMessageORM.channel
                == _parse_enum(OutboxChannel, channel, field="channel")
            )
        if status:
            q = q.filter(
                OutboxMessageORM.status
                == _parse_enum(OutboxStatus, status, field="status")
            )
        if delivery_status:
            q = q.filter(
                OutboxMessageORM.delivery_status
                == _parse_enum(
                    DeliveryStatus,
                    delivery_status,
                    field="delivery_status",
                )
            )

        rows = q.order_by(OutboxMessageORM.created_at.desc()).limit(limit).all()
        return OutboxListResponse(items=[_to_dto(r) for r in rows])

    @staticmethod
    def summary_outbox(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID | None,
    ) -> OutboxSummaryResponse:
        base_q = uow.session.query(OutboxMessageORM).filter(
            OutboxMessageORM.company_id == company_id
        )
        if journal_id is not None:
            base_q = base_q.filter(OutboxMessageORM.correlation_id == journal_id)

        def _group_counts(column) -> dict[str, int]:
            rows = (
                base_q.with_entities(column, func.count())
                .group_by(column)
                .all()
            )
            return {_enum_value(key): int(value) for key, value in rows}

        now = datetime.now(timezone.utc)
        pending_overdue_15m = base_q.filter(
            OutboxMessageORM.status == OutboxStatus.PENDING,
            OutboxMessageORM.scheduled_at < (now - timedelta(minutes=15)),
        ).count()
        failed_total = base_q.filter(
            OutboxMessageORM.status == OutboxStatus.FAILED
        ).count()

        return OutboxSummaryResponse(
            total=base_q.count(),
            by_channel=_group_counts(OutboxMessageORM.channel),
            by_status=_group_counts(OutboxMessageORM.status),
            by_delivery_status=_group_counts(OutboxMessageORM.delivery_status),
            pending_overdue_15m=pending_overdue_15m,
            failed_total=failed_total,
        )

    @staticmethod
    def get_outbox(
        uow,
        *,
        company_id: uuid.UUID,
        outbox_id: uuid.UUID,
    ) -> OutboxItemDTO:
        row = (
            uow.session.query(OutboxMessageORM)
            .filter(
                OutboxMessageORM.company_id == company_id,
                OutboxMessageORM.id == outbox_id,
            )
            .one_or_none()
        )
        if not row:
            raise NotFound(
                "Outbox message not found",
                details={"outbox_id": str(outbox_id)},
            )
        return _to_dto(row)

    @staticmethod
    def retry_outbox(
        uow,
        *,
        company_id: uuid.UUID,
        outbox_id: uuid.UUID,
    ) -> tuple[OutboxItemDTO, dict, dict]:
        row = (
            uow.session.query(OutboxMessageORM)
            .filter(
                OutboxMessageORM.company_id == company_id,
                OutboxMessageORM.id == outbox_id,
            )
            .one_or_none()
        )
        if not row:
            raise NotFound(
                "Outbox message not found",
                details={"outbox_id": str(outbox_id)},
            )
        if row.status == OutboxStatus.SENT:
            raise ValidationError(
                "Cannot retry already sent outbox message",
                details={"outbox_id": str(outbox_id), "status": _enum_value(row.status)},
            )

        before = {
            "status": _enum_value(row.status),
            "delivery_status": _enum_value(row.delivery_status),
            "attempts": row.attempts,
            "max_attempts": row.max_attempts,
            "scheduled_at": (
                row.scheduled_at.isoformat() if row.scheduled_at is not None else None
            ),
            "last_error": row.last_error,
        }

        if row.status == OutboxStatus.FAILED and row.attempts >= row.max_attempts:
            row.max_attempts = row.attempts + 1
        row.status = OutboxStatus.PENDING
        row.delivery_status = DeliveryStatus.PENDING
        row.scheduled_at = datetime.now(timezone.utc)
        row.last_error = None
        row.provider_error = None
        uow.session.add(row)

        after = {
            "status": _enum_value(row.status),
            "delivery_status": _enum_value(row.delivery_status),
            "attempts": row.attempts,
            "max_attempts": row.max_attempts,
            "scheduled_at": (
                row.scheduled_at.isoformat() if row.scheduled_at is not None else None
            ),
            "last_error": row.last_error,
        }
        return _to_dto(row), before, after
