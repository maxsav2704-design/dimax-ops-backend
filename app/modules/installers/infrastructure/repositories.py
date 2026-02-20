from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.installers.infrastructure.models import InstallerORM


class InstallerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, company_id: uuid.UUID, installer_id: uuid.UUID
    ) -> InstallerORM | None:
        """Get installer by company and id (including soft-deleted)."""
        stmt = select(InstallerORM).where(
            InstallerORM.company_id == company_id,
            InstallerORM.id == installer_id,
        )
        return self.session.execute(stmt).scalars().first()

    def list(
        self,
        company_id: uuid.UUID,
        q: Optional[str],
        is_active: Optional[bool],
        limit: int,
        offset: int,
    ) -> list[InstallerORM]:
        stmt = select(InstallerORM).where(InstallerORM.company_id == company_id)
        stmt = stmt.where(InstallerORM.deleted_at.is_(None))
        if is_active is not None:
            stmt = stmt.where(InstallerORM.is_active == is_active)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(InstallerORM.full_name.ilike(like))
        stmt = stmt.order_by(InstallerORM.full_name.asc()).limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars().all())

    def add(self, obj: InstallerORM) -> None:
        self.session.add(obj)

    def get_by_user_id(
        self, *, company_id: uuid.UUID, user_id: uuid.UUID
    ) -> InstallerORM | None:
        """Active installer linked to this user (for auth lookup)."""
        return (
            self.session.query(InstallerORM)
            .filter(
                InstallerORM.company_id == company_id,
                InstallerORM.user_id == user_id,
                InstallerORM.is_active.is_(True),
                InstallerORM.deleted_at.is_(None),
            )
            .one_or_none()
        )

    def get_installer_by_user_id_any(
        self, *, company_id: uuid.UUID, user_id: uuid.UUID
    ) -> InstallerORM | None:
        """Any installer (including deleted) with this user_id; for link uniqueness check."""
        stmt = select(InstallerORM).where(
            InstallerORM.company_id == company_id,
            InstallerORM.user_id == user_id,
        )
        return self.session.execute(stmt).scalars().first()
