from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.installers.domain.errors import (
    DoorTypeNotFound,
    InstallerNotFound,
    InstallerRateAlreadyExists,
)
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.rates.infrastructure.models import InstallerRateORM


class RatesAdminService:
    def __init__(self, session) -> None:
        self.session = session

    def _ensure_installer_exists_and_not_deleted(
        self, company_id: uuid.UUID, installer_id: uuid.UUID
    ) -> InstallerORM:
        row = self.session.execute(
            select(InstallerORM).where(
                InstallerORM.company_id == company_id,
                InstallerORM.id == installer_id,
            )
        ).scalars().first()
        if not row:
            raise InstallerNotFound("installer_id invalid or not found")
        if row.deleted_at is not None:
            raise InstallerNotFound("installer is deleted")
        return row

    def _ensure_door_type_exists(
        self, company_id: uuid.UUID, door_type_id: uuid.UUID
    ) -> None:
        row = self.session.execute(
            select(DoorTypeORM).where(
                DoorTypeORM.company_id == company_id,
                DoorTypeORM.id == door_type_id,
            )
        ).scalars().first()
        if not row:
            raise DoorTypeNotFound("door_type_id not found")
        if row.deleted_at is not None:
            raise DoorTypeNotFound("door type is deleted")

    def create(self, company_id: uuid.UUID, data) -> InstallerRateORM:
        self._ensure_installer_exists_and_not_deleted(
            company_id, data.installer_id
        )
        self._ensure_door_type_exists(company_id, data.door_type_id)
        existing = self.session.execute(
            select(InstallerRateORM).where(
                InstallerRateORM.company_id == company_id,
                InstallerRateORM.installer_id == data.installer_id,
                InstallerRateORM.door_type_id == data.door_type_id,
            )
        ).scalars().first()
        if existing:
            raise InstallerRateAlreadyExists(
                "rate already exists for this installer and door type"
            )
        obj = InstallerRateORM(
            company_id=company_id,
            installer_id=data.installer_id,
            door_type_id=data.door_type_id,
            price=data.price,
        )
        self.session.add(obj)
        self.session.flush()
        return obj

    def update(
        self, rate: InstallerRateORM, data
    ) -> InstallerRateORM:
        payload = data.model_dump(exclude_unset=True)
        if "price" in payload:
            rate.price = payload["price"]
        self.session.add(rate)
        return rate

    def delete(self, rate: InstallerRateORM) -> None:
        self.session.delete(rate)
