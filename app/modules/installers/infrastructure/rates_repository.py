from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.rates.infrastructure.models import InstallerRateORM


class InstallerRatesRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, company_id: uuid.UUID, rate_id: uuid.UUID
    ) -> InstallerRateORM | None:
        stmt = select(InstallerRateORM).where(
            InstallerRateORM.company_id == company_id,
            InstallerRateORM.id == rate_id,
        )
        return self.session.execute(stmt).scalars().first()

    def list(
        self,
        company_id: uuid.UUID,
        installer_id: Optional[uuid.UUID] = None,
        door_type_id: Optional[uuid.UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InstallerRateORM]:
        stmt = select(InstallerRateORM).where(
            InstallerRateORM.company_id == company_id
        )
        if installer_id is not None:
            stmt = stmt.where(InstallerRateORM.installer_id == installer_id)
        if door_type_id is not None:
            stmt = stmt.where(InstallerRateORM.door_type_id == door_type_id)
        stmt = stmt.order_by(
            InstallerRateORM.installer_id.asc(),
            InstallerRateORM.door_type_id.asc(),
        ).limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars().all())

    def get_by_keys(
        self,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        door_type_id: uuid.UUID,
    ) -> InstallerRateORM | None:
        stmt = select(InstallerRateORM).where(
            InstallerRateORM.company_id == company_id,
            InstallerRateORM.installer_id == installer_id,
            InstallerRateORM.door_type_id == door_type_id,
        )
        return self.session.execute(stmt).scalars().first()

    def add(self, obj: InstallerRateORM) -> None:
        self.session.add(obj)

    def delete(self, obj: InstallerRateORM) -> None:
        self.session.delete(obj)
