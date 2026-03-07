from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.models import AuditAlertReadCursorORM, AuditLogORM


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, log: AuditLogORM) -> None:
        self.session.add(log)

    def exists_recent_action(
        self,
        *,
        company_id: uuid.UUID,
        action: str,
        since: datetime,
    ) -> bool:
        row = (
            self.session.query(AuditLogORM.id)
            .filter(
                AuditLogORM.company_id == company_id,
                AuditLogORM.action == action,
                AuditLogORM.created_at >= since,
            )
            .first()
        )
        return row is not None

    def list_limit_alerts(
        self,
        *,
        company_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> list[AuditLogORM]:
        return (
            self.session.query(AuditLogORM)
            .filter(
                AuditLogORM.company_id == company_id,
                AuditLogORM.action.like("PLAN_LIMIT_ALERT_%"),
            )
            .order_by(AuditLogORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def count_limit_alerts_since(
        self,
        *,
        company_id: uuid.UUID,
        since: datetime | None,
    ) -> int:
        q = self.session.query(AuditLogORM.id).filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.action.like("PLAN_LIMIT_ALERT_%"),
        )
        if since is not None:
            q = q.filter(AuditLogORM.created_at > since)
        return int(q.count())

    def get_alert_read_cursor(
        self,
        *,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AuditAlertReadCursorORM | None:
        return (
            self.session.query(AuditAlertReadCursorORM)
            .filter(
                AuditAlertReadCursorORM.company_id == company_id,
                AuditAlertReadCursorORM.user_id == user_id,
            )
            .one_or_none()
        )

    def upsert_alert_read_cursor(
        self,
        *,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        last_read_at: datetime,
    ) -> AuditAlertReadCursorORM:
        cursor = self.get_alert_read_cursor(company_id=company_id, user_id=user_id)
        if cursor is None:
            cursor = AuditAlertReadCursorORM(
                company_id=company_id,
                user_id=user_id,
                last_read_at=last_read_at,
            )
        else:
            cursor.last_read_at = last_read_at
        self.session.add(cursor)
        self.session.flush()
        return cursor
