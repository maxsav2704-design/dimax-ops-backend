from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.reasons.infrastructure.models import ReasonORM


class ReasonRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self,
        *,
        company_id: uuid.UUID,
        reason_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> ReasonORM | None:
        stmt = select(ReasonORM).where(
            ReasonORM.company_id == company_id,
            ReasonORM.id == reason_id,
        )
        if not include_deleted:
            stmt = stmt.where(ReasonORM.deleted_at.is_(None))
        return self.session.execute(stmt).scalars().first()

    def get_by_code(
        self,
        *,
        company_id: uuid.UUID,
        code: str,
        include_deleted: bool = False,
    ) -> ReasonORM | None:
        stmt = select(ReasonORM).where(
            ReasonORM.company_id == company_id,
            ReasonORM.code == code,
        )
        if not include_deleted:
            stmt = stmt.where(ReasonORM.deleted_at.is_(None))
        return self.session.execute(stmt).scalars().first()

    def list(
        self,
        *,
        company_id: uuid.UUID,
        q: str | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> list[ReasonORM]:
        stmt = select(ReasonORM).where(
            ReasonORM.company_id == company_id,
            ReasonORM.deleted_at.is_(None),
        )
        if is_active is not None:
            stmt = stmt.where(ReasonORM.is_active == is_active)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(ReasonORM.code.ilike(like), ReasonORM.name.ilike(like))
            )
        stmt = stmt.order_by(ReasonORM.code.asc()).limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars().all())

    def list_active(self, *, company_id: uuid.UUID) -> list[ReasonORM]:
        stmt = (
            select(ReasonORM)
            .where(
                ReasonORM.company_id == company_id,
                ReasonORM.deleted_at.is_(None),
                ReasonORM.is_active.is_(True),
            )
            .order_by(ReasonORM.code.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def save(self, obj: ReasonORM) -> None:
        self.session.add(obj)

    def soft_delete(self, obj: ReasonORM) -> None:
        obj.deleted_at = datetime.now(timezone.utc)
        obj.is_active = False
        self.session.add(obj)

    def list_all(
        self,
        *,
        company_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> list[ReasonORM]:
        stmt = select(ReasonORM).where(ReasonORM.company_id == company_id)
        if not include_deleted:
            stmt = stmt.where(ReasonORM.deleted_at.is_(None))
        stmt = stmt.order_by(ReasonORM.code.asc())
        return list(self.session.execute(stmt).scalars().all())
