from __future__ import annotations

import uuid
from sqlalchemy.orm import Session

from app.modules.identity.infrastructure.models import CompanyORM


class CompanyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[CompanyORM]:
        return (
            self.session.query(CompanyORM)
            .filter(CompanyORM.is_active.is_(True))
            .all()
        )

    def list_ids(self) -> list[uuid.UUID]:
        """Return list of active company IDs (for workers, no ORM load)."""
        rows = (
            self.session.query(CompanyORM.id)
            .filter(CompanyORM.is_active.is_(True))
            .all()
        )
        return [r[0] for r in rows]
