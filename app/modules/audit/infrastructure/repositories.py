from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.models import AuditLogORM


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, log: AuditLogORM) -> None:
        self.session.add(log)
