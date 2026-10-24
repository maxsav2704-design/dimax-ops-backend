import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.config import settings
from app.modules.audit.application.service import AuditService
from app.modules.identity.infrastructure.models import AdminProfileORM, UserORM
from app.modules.outbox.api.recovery_schemas import RecoveryDecisionDTO, RecoveryItemDTO, RecoveryStatusDTO
from app.modules.outbox.domain.enums import DeliveryStatus, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM as Message
from app.modules.outbox.infrastructure.recovery_gate import lock_delivery
from app.modules.outbox.infrastructure.recovery_models import (
    OutboxRecoveryORM as Recovery, OutboxRecoveryItemORM as Item, OutboxRecoveryDecisionORM as Decision,
)
from app.shared.domain.errors import Conflict, ForbiddenScope, NotFound, ValidationError


def _authorize(uow, user, *, owner=False, read=False):
    allowed = {"OWNER"} if owner else {"OWNER", "OPERATIONS"}
    if read:
        allowed.add("FINANCE")
    scope = uow.session.scalar(select(AdminProfileORM.admin_scope).join(
        UserORM, UserORM.id == AdminProfileORM.user_id,
    ).where(
        UserORM.id == user.id, UserORM.company_id == user.company_id,
        UserORM.is_active.is_(True), UserORM.role == "ADMIN",
        AdminProfileORM.company_id == user.company_id,
    ))
    if scope not in allowed:
        raise ForbiddenScope("OWNER access required" if owner else "Outbox recovery access required")


def _epoch():
    if settings.OUTBOX_RECOVERY_EPOCH is None:
        raise Conflict("Set a fresh OUTBOX_RECOVERY_EPOCH on API and workers before recovery")
    return settings.OUTBOX_RECOVERY_EPOCH


def _digest(message):
    data = [str(message.company_id), str(message.id), message.channel.value,
            str(message.correlation_id), message.payload]
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _run(uow, user):
    latest = uow.session.scalar(select(Recovery.epoch).where(
        Recovery.company_id == user.company_id,
    ).order_by(Recovery.opened_at.desc(), Recovery.id.desc()).limit(1))
    if latest is not None and latest != _epoch():
        raise Conflict("Recovery configuration is stale; use the latest recovery epoch")
    run = uow.session.scalar(select(Recovery).where(
        Recovery.company_id == user.company_id, Recovery.epoch == _epoch(),
    ))
    if run is None:
        raise Conflict("Open a recovery review first")
    return run


def _audit(uow, user, run, action, reason, after=None):
    AuditService.add(uow, company_id=user.company_id, actor_user_id=user.id,
                     entity_type="outbox_recovery", entity_id=run.id,
                     action=action, reason=reason, after=after)


class OutboxRecoveryService:
    @staticmethod
    def status(uow, user):
        _authorize(uow, user, read=True)
        epoch = settings.OUTBOX_RECOVERY_EPOCH
        query = select(Recovery).where(Recovery.company_id == user.company_id)
        if epoch is None:
            exists = uow.session.scalar(query.limit(1)) is not None
            return RecoveryStatusDTO(epoch=None, recovery_id=None,
                                     state="CONFIGURATION_REQUIRED" if exists else "NOT_ACTIVATED")
        run = uow.session.scalar(query.where(Recovery.epoch == epoch))
        if run is None:
            return RecoveryStatusDTO(epoch=epoch, recovery_id=None, state="REVIEW_REQUIRED")
        counts = dict(uow.session.execute(select(Item.action, func.count()).where(
            Item.company_id == user.company_id, Item.recovery_id == run.id,
        ).group_by(Item.action)).all())
        return RecoveryStatusDTO(epoch=epoch, recovery_id=run.id,
                                 state="RELEASED" if run.released_at else "REVIEW",
                                 unresolved=counts.get(None, 0), held=counts.get("HOLD", 0))

    @staticmethod
    def begin(uow, user, body):
        _authorize(uow, user, owner=True)
        epoch = _epoch()
        lock_delivery(uow.session)
        existing = uow.session.scalar(select(Recovery).where(
            Recovery.company_id == user.company_id, Recovery.epoch == epoch,
        ))
        if existing is not None:
            raise Conflict("This recovery epoch already has a review")
        run = Recovery(company_id=user.company_id, epoch=epoch, opened_by=user.id, reason=body.reason)
        uow.session.add(run)
        uow.session.flush()
        rows = uow.session.scalars(select(Message).where(
            Message.company_id == user.company_id, Message.status != OutboxStatus.SENT,
        ).with_for_update()).all()
        for message in rows:
            uow.session.add(Item(company_id=user.company_id, recovery_id=run.id,
                                 outbox_id=message.id, payload_digest=_digest(message)))
        _audit(uow, user, run, "OUTBOX_RECOVERY_OPEN", body.reason, {"epoch": str(epoch), "items": len(rows)})
        uow.session.flush()
        return OutboxRecoveryService.status(uow, user)

    @staticmethod
    def items(uow, user, *, offset=0, limit=50):
        _authorize(uow, user, read=True)
        run = _run(uow, user)
        rows = uow.session.scalars(select(Item).where(
            Item.company_id == user.company_id, Item.recovery_id == run.id,
        ).order_by(Item.id).offset(offset).limit(limit)).all()
        return [RecoveryItemDTO.model_validate(row) for row in rows]

    @staticmethod
    def decisions(uow, user, *, offset=0, limit=50):
        _authorize(uow, user, read=True)
        rows = uow.session.scalars(select(Decision).where(
            Decision.company_id == user.company_id,
        ).order_by(Decision.created_at.desc(), Decision.id).offset(offset).limit(limit)).all()
        return [RecoveryDecisionDTO.model_validate(row) for row in rows]

    @staticmethod
    def decide(uow, user, item_id, body):
        _authorize(uow, user)
        lock_delivery(uow.session)
        run = _run(uow, user)
        item = uow.session.scalar(select(Item).where(
            Item.id == item_id, Item.company_id == user.company_id, Item.recovery_id == run.id,
        ).with_for_update())
        if item is None:
            raise NotFound("Recovery item not found")
        previous = uow.session.scalar(select(Decision).where(
            Decision.company_id == user.company_id, Decision.request_id == body.request_id,
        ))
        if previous:
            if (previous.item_id, previous.revision - 1, previous.action, previous.reason,
                previous.evidence, previous.accepted_at, previous.actor_id) != (
                item_id, body.expected_revision, body.action, body.reason, body.evidence, body.accepted_at, user.id
            ):
                raise Conflict("Request ID was already used for another decision")
            return RecoveryDecisionDTO.model_validate(previous)
        if item.revision != body.expected_revision or item.action not in {None, "HOLD"}:
            raise Conflict("Recovery item was already resolved or changed; reload the review")
        now = datetime.now(timezone.utc)
        if (body.action == "ACCEPTED") != (body.accepted_at is not None):
            raise ValidationError("Only ACCEPTED requires the provider acceptance timestamp")
        if body.accepted_at and body.accepted_at > now:
            raise ValidationError("Provider acceptance cannot be in the future")
        message = uow.session.scalar(select(Message).where(
            Message.id == item.outbox_id, Message.company_id == user.company_id,
        ).with_for_update())
        if message is None or _digest(message) != item.payload_digest:
            raise Conflict("Message content changed after the recovery snapshot")
        if message.status == OutboxStatus.SENT:
            raise Conflict("Message is already sent; it cannot be replayed")
        if body.action == "ACCEPTED":
            message.status = OutboxStatus.SENT
            message.sent_at = body.accepted_at
            # SMTP acceptance is NOT delivery/read confirmation. No journal,
            # signature, price approval or earnings action is executed here.
        elif body.action == "RETRY":
            message.status = OutboxStatus.PENDING
            message.max_attempts = max(message.max_attempts, message.attempts + 1)
            message.delivery_status = DeliveryStatus.PENDING
            message.last_error = None
            message.provider_error = None
        item.action = body.action
        item.revision += 1
        decision = Decision(company_id=user.company_id, item_id=item.id,
                            request_id=body.request_id, revision=item.revision, action=body.action,
                            reason=body.reason, evidence=body.evidence, accepted_at=body.accepted_at,
                            actor_id=user.id)
        uow.session.add(decision)
        _audit(uow, user, run, "OUTBOX_RECOVERY_DECIDE", body.reason,
               {"item_id": str(item.id), "outbox_id": str(message.id), "action": body.action,
                "revision": item.revision, "request_id": str(body.request_id)})
        uow.session.flush()
        return RecoveryDecisionDTO.model_validate(decision)

    @staticmethod
    def release(uow, user, body):
        _authorize(uow, user, owner=True)
        lock_delivery(uow.session)
        run = _run(uow, user)
        if run.released_at:
            raise Conflict("Recovery was already released")
        if uow.session.scalar(select(Item.id).where(
            Item.recovery_id == run.id, Item.action.is_(None),
        ).limit(1)):
            raise Conflict("Every disputed message needs a recorded decision before release")
        run.released_at = datetime.now(timezone.utc)
        run.released_by = user.id
        _audit(uow, user, run, "OUTBOX_RECOVERY_RELEASE", body.reason)
        uow.session.flush()
        return OutboxRecoveryService.status(uow, user)
