from __future__ import annotations

import uuid

from app.modules.door_types.domain.errors import DoorTypeCodeAlreadyExists
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.shared.domain.errors import NotFound


def normalize_code(raw: str) -> str:
    return raw.strip().lower()


class DoorTypesAdminService:
    @staticmethod
    def create(
        uow,
        *,
        company_id: uuid.UUID,
        code: str,
        name: str,
        is_active: bool,
    ) -> DoorTypeORM:
        normalized = normalize_code(code)
        existing = uow.door_types.get_by_code(
            company_id=company_id,
            code=normalized,
            include_deleted=True,
        )
        if existing is not None:
            raise DoorTypeCodeAlreadyExists("door type code already exists")

        row = DoorTypeORM(
            company_id=company_id,
            code=normalized,
            name=name.strip(),
            is_active=is_active,
        )
        uow.door_types.save(row)
        uow.session.flush()
        return row

    @staticmethod
    def update(
        uow,
        *,
        company_id: uuid.UUID,
        door_type_id: uuid.UUID,
        payload: dict,
    ) -> DoorTypeORM:
        row = uow.door_types.get(
            company_id=company_id,
            door_type_id=door_type_id,
        )
        if row is None:
            raise NotFound("Door type not found")

        if "code" in payload and payload["code"] is not None:
            new_code = normalize_code(payload["code"])
            if new_code != row.code:
                existing = uow.door_types.get_by_code(
                    company_id=company_id,
                    code=new_code,
                    include_deleted=True,
                )
                if existing is not None and existing.id != row.id:
                    raise DoorTypeCodeAlreadyExists("door type code already exists")
                row.code = new_code

        if "name" in payload and payload["name"] is not None:
            row.name = payload["name"].strip()

        if "is_active" in payload and payload["is_active"] is not None:
            row.is_active = bool(payload["is_active"])

        uow.door_types.save(row)
        return row

    @staticmethod
    def delete(
        uow,
        *,
        company_id: uuid.UUID,
        door_type_id: uuid.UUID,
    ) -> None:
        row = uow.door_types.get(
            company_id=company_id,
            door_type_id=door_type_id,
        )
        if row is None:
            raise NotFound("Door type not found")
        uow.door_types.soft_delete(row)

