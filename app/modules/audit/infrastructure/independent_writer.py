from __future__ import annotations

import uuid

from app.modules.audit.infrastructure.models import AuditLogORM
from app.shared.infrastructure.db.session import SessionLocal


def write_audit_log_independent(
    *,
    company_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    reason: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    session = SessionLocal()
    try:
        session.add(
            AuditLogORM(
                company_id=company_id,
                actor_user_id=actor_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                reason=reason,
                before=before,
                after=after,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

