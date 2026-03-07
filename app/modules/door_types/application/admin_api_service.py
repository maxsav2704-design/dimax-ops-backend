from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.modules.audit.application.service import AuditService
from app.modules.door_types.api.schemas import (
    DoorTypeCreateDTO,
    DoorTypeDTO,
    DoorTypeUpdateDTO,
)
from app.modules.door_types.application.admin_service import DoorTypesAdminService
from app.modules.door_types.domain.errors import DoorTypeCodeAlreadyExists
from app.shared.domain.errors import NotFound


def _snapshot(obj) -> dict:
    return {
        "code": obj.code,
        "name": obj.name,
        "is_active": obj.is_active,
        "deleted_at": obj.deleted_at.isoformat() if obj.deleted_at else None,
    }


class DoorTypesAdminApiService:
    @staticmethod
    def export_door_types(
        uow,
        *,
        company_id: uuid.UUID,
    ) -> list[DoorTypeDTO]:
        items = uow.door_types.list_all(company_id=company_id, include_deleted=False)
        return [DoorTypeDTO.model_validate(x) for x in items]

    @staticmethod
    def list_door_types(
        uow,
        *,
        company_id: uuid.UUID,
        q: str | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> list[DoorTypeDTO]:
        items = uow.door_types.list(
            company_id=company_id,
            q=q,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        return [DoorTypeDTO.model_validate(x) for x in items]

    @staticmethod
    def get_door_type(
        uow,
        *,
        company_id: uuid.UUID,
        door_type_id: uuid.UUID,
    ) -> DoorTypeDTO:
        row = uow.door_types.get(
            company_id=company_id,
            door_type_id=door_type_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="door type not found")
        return DoorTypeDTO.model_validate(row)

    @staticmethod
    def create_door_type(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        data: DoorTypeCreateDTO,
    ) -> DoorTypeDTO:
        try:
            row = DoorTypesAdminService.create(
                uow,
                company_id=company_id,
                code=data.code,
                name=data.name,
                is_active=data.is_active,
            )
        except DoorTypeCodeAlreadyExists as e:
            raise HTTPException(status_code=409, detail=str(e))
        except IntegrityError as e:
            raise HTTPException(status_code=409, detail="door type code already exists") from e

        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="door_type",
            entity_id=row.id,
            action="DOOR_TYPE_CREATE",
            before=None,
            after=_snapshot(row),
        )
        uow.session.flush()
        return DoorTypeDTO.model_validate(row)

    @staticmethod
    def import_door_types(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        items: list[dict],
        create_only: bool,
    ) -> dict:
        created = 0
        updated = 0
        unchanged = 0
        skipped_existing = 0
        seen_codes: set[str] = set()

        for item in items:
            code = item["code"].strip().lower()
            if code in seen_codes:
                raise HTTPException(
                    status_code=422,
                    detail=f"duplicate code in import payload: {code}",
                )
            seen_codes.add(code)

            existing = uow.door_types.get_by_code(
                company_id=company_id,
                code=code,
                include_deleted=True,
            )

            if existing is None:
                row = DoorTypesAdminService.create(
                    uow,
                    company_id=company_id,
                    code=code,
                    name=item["name"],
                    is_active=bool(item.get("is_active", True)),
                )
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="door_type",
                    entity_id=row.id,
                    action="DOOR_TYPE_CREATE",
                    reason="BULK_IMPORT",
                    before=None,
                    after=_snapshot(row),
                )
                created += 1
                continue

            if create_only:
                skipped_existing += 1
                continue

            before = _snapshot(existing)
            changed = False
            new_name = item["name"].strip()
            new_is_active = bool(item.get("is_active", True))
            if existing.name != new_name:
                existing.name = new_name
                changed = True
            if existing.is_active != new_is_active:
                existing.is_active = new_is_active
                changed = True
            if existing.deleted_at is not None:
                existing.deleted_at = None
                changed = True

            if changed:
                uow.door_types.save(existing)
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="door_type",
                    entity_id=existing.id,
                    action="DOOR_TYPE_UPDATE",
                    reason="BULK_IMPORT",
                    before=before,
                    after=_snapshot(existing),
                )
                updated += 1
            else:
                unchanged += 1

        try:
            uow.session.flush()
        except IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail="door type import conflicts with unique constraints",
            ) from e

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "skipped_existing": skipped_existing,
        }

    @staticmethod
    def bulk_door_types(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        ids: list[uuid.UUID],
        operation: str,
    ) -> dict:
        affected = 0
        not_found = 0
        unchanged = 0

        unique_ids = list(dict.fromkeys(ids))
        for door_type_id in unique_ids:
            row = uow.door_types.get(
                company_id=company_id,
                door_type_id=door_type_id,
            )
            if row is None:
                not_found += 1
                continue

            before = _snapshot(row)
            if operation == "activate":
                if row.is_active:
                    unchanged += 1
                    continue
                row.is_active = True
                if row.deleted_at is not None:
                    row.deleted_at = None
                uow.door_types.save(row)
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="door_type",
                    entity_id=row.id,
                    action="DOOR_TYPE_UPDATE",
                    reason="BULK_ACTIVATE",
                    before=before,
                    after=_snapshot(row),
                )
                affected += 1
                continue

            if operation == "deactivate":
                if not row.is_active:
                    unchanged += 1
                    continue
                row.is_active = False
                uow.door_types.save(row)
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="door_type",
                    entity_id=row.id,
                    action="DOOR_TYPE_UPDATE",
                    reason="BULK_DEACTIVATE",
                    before=before,
                    after=_snapshot(row),
                )
                affected += 1
                continue

            if operation == "delete":
                DoorTypesAdminService.delete(
                    uow,
                    company_id=company_id,
                    door_type_id=row.id,
                )
                row_after = uow.door_types.get(
                    company_id=company_id,
                    door_type_id=row.id,
                    include_deleted=True,
                )
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="door_type",
                    entity_id=row.id,
                    action="DOOR_TYPE_DELETE",
                    reason="BULK_DELETE",
                    before=before,
                    after=_snapshot(row_after) if row_after else None,
                )
                affected += 1
                continue

            raise HTTPException(status_code=422, detail="unsupported bulk operation")

        uow.session.flush()
        return {
            "affected": affected,
            "not_found": not_found,
            "unchanged": unchanged,
        }

    @staticmethod
    def update_door_type(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        door_type_id: uuid.UUID,
        data: DoorTypeUpdateDTO,
    ) -> DoorTypeDTO:
        existing = uow.door_types.get(
            company_id=company_id,
            door_type_id=door_type_id,
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="door type not found")
        before = _snapshot(existing)

        try:
            row = DoorTypesAdminService.update(
                uow,
                company_id=company_id,
                door_type_id=door_type_id,
                payload=data.model_dump(exclude_unset=True),
            )
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except DoorTypeCodeAlreadyExists as e:
            raise HTTPException(status_code=409, detail=str(e))
        except IntegrityError as e:
            raise HTTPException(status_code=409, detail="door type code already exists") from e

        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="door_type",
            entity_id=row.id,
            action="DOOR_TYPE_UPDATE",
            before=before,
            after=_snapshot(row),
        )
        uow.session.flush()
        return DoorTypeDTO.model_validate(row)

    @staticmethod
    def delete_door_type(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        door_type_id: uuid.UUID,
    ) -> None:
        row = uow.door_types.get(
            company_id=company_id,
            door_type_id=door_type_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="door type not found")
        before = _snapshot(row)
        DoorTypesAdminService.delete(
            uow,
            company_id=company_id,
            door_type_id=door_type_id,
        )
        after_row = uow.door_types.get(
            company_id=company_id,
            door_type_id=door_type_id,
            include_deleted=True,
        )
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="door_type",
            entity_id=door_type_id,
            action="DOOR_TYPE_DELETE",
            before=before,
            after=_snapshot(after_row) if after_row else None,
        )
        uow.session.flush()
