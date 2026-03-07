from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.door_types.infrastructure.models import DoorTypeORM


class DoorTypeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self,
        *,
        company_id: uuid.UUID,
        door_type_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> DoorTypeORM | None:
        stmt = select(DoorTypeORM).where(
            DoorTypeORM.company_id == company_id,
            DoorTypeORM.id == door_type_id,
        )
        if not include_deleted:
            stmt = stmt.where(DoorTypeORM.deleted_at.is_(None))
        return self.session.execute(stmt).scalars().first()

    def get_by_code(
        self,
        *,
        company_id: uuid.UUID,
        code: str,
        include_deleted: bool = False,
    ) -> DoorTypeORM | None:
        stmt = select(DoorTypeORM).where(
            DoorTypeORM.company_id == company_id,
            DoorTypeORM.code == code,
        )
        if not include_deleted:
            stmt = stmt.where(DoorTypeORM.deleted_at.is_(None))
        return self.session.execute(stmt).scalars().first()

    def list(
        self,
        *,
        company_id: uuid.UUID,
        q: str | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> list[DoorTypeORM]:
        stmt = select(DoorTypeORM).where(
            DoorTypeORM.company_id == company_id,
            DoorTypeORM.deleted_at.is_(None),
        )
        if is_active is not None:
            stmt = stmt.where(DoorTypeORM.is_active == is_active)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(DoorTypeORM.code.ilike(like), DoorTypeORM.name.ilike(like))
            )
        stmt = (
            stmt.order_by(DoorTypeORM.code.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_active(self, *, company_id: uuid.UUID) -> list[DoorTypeORM]:
        stmt = (
            select(DoorTypeORM)
            .where(
                DoorTypeORM.company_id == company_id,
                DoorTypeORM.deleted_at.is_(None),
                DoorTypeORM.is_active.is_(True),
            )
            .order_by(DoorTypeORM.code.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def save(self, obj: DoorTypeORM) -> None:
        self.session.add(obj)

    def soft_delete(self, obj: DoorTypeORM) -> None:
        obj.deleted_at = datetime.now(timezone.utc)
        obj.is_active = False
        self.session.add(obj)

    def list_all(
        self,
        *,
        company_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> list[DoorTypeORM]:
        stmt = select(DoorTypeORM).where(DoorTypeORM.company_id == company_id)
        if not include_deleted:
            stmt = stmt.where(DoorTypeORM.deleted_at.is_(None))
        stmt = stmt.order_by(DoorTypeORM.code.asc())
        return list(self.session.execute(stmt).scalars().all())
