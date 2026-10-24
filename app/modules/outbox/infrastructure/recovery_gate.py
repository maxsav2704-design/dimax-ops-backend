from sqlalchemy import and_, exists, or_, select, text

from app.core.config import settings
from app.modules.outbox.infrastructure.models import OutboxMessageORM as Message
from app.modules.outbox.infrastructure.recovery_models import OutboxRecoveryORM as Recovery, OutboxRecoveryItemORM as Item
from app.shared.domain.errors import Conflict


# One delivery transaction at a time, including the SMTP call and its commit.
# Admin recovery/retry mutations take the same lock BEFORE any row locks.
DELIVERY_LOCK = 4919409929323763028


def lock_delivery(session, *, wait=True):
    function = "pg_advisory_xact_lock" if wait else "pg_try_advisory_xact_lock"
    result = session.execute(text(f"SELECT {function}(:key)"), {"key": DELIVERY_LOCK}).scalar()
    return True if wait else bool(result)


def dispatch_allowed():
    epoch = settings.OUTBOX_RECOVERY_EPOCH
    if epoch is None:
        # Backward-compatible before first recovery; removing configuration later
        # must never bypass an existing hold or a previously activated gate.
        return ~exists(select(Recovery.id).where(Recovery.company_id == Message.company_id))
    released = exists(select(Recovery.id).where(
        Recovery.company_id == Message.company_id, Recovery.epoch == epoch,
        Recovery.released_at.is_not(None),
    ))
    latest_epoch = select(Recovery.epoch).where(
        Recovery.company_id == Message.company_id,
    ).order_by(Recovery.opened_at.desc(), Recovery.id.desc()).limit(1).correlate(Message).scalar_subquery()
    blocked = exists(select(Item.id).join(Recovery, Recovery.id == Item.recovery_id).where(
        Recovery.company_id == Message.company_id, Recovery.epoch == epoch,
        Item.outbox_id == Message.id, or_(Item.action.is_(None), Item.action == "HOLD"),
    ))
    return and_(released, latest_epoch == epoch, ~blocked)


def ensure_retry_allowed(session, *, company_id, outbox_id):
    lock_delivery(session)
    row = session.scalar(select(Message.id).where(
        Message.company_id == company_id, Message.id == outbox_id, dispatch_allowed(),
    ))
    if row is None and session.scalar(select(Message.id).where(
        Message.company_id == company_id, Message.id == outbox_id,
    )):
        raise Conflict("Outbox recovery reconciliation is required before retry")
