from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.modules.audit.application.service import AuditService
from app.modules.reasons.api.schemas import ReasonCreateDTO, ReasonDTO, ReasonUpdateDTO
from app.modules.reasons.application.admin_service import ReasonsAdminService
from app.modules.reasons.domain.errors import ReasonCodeAlreadyExists
from app.shared.domain.errors import NotFound


def _snapshot(obj) -> dict:
    return {
        "code": obj.code,
        "name": obj.name,
        "is_active": obj.is_active,
        "deleted_at": obj.deleted_at.isoformat() if obj.deleted_at else None,
    }


class ReasonsAdminApiService:
    @staticmethod
    def export_reasons(
        uow,
        *,
        company_id: uuid.UUID,
    ) -> list[ReasonDTO]:
        items = uow.reasons.list_all(company_id=company_id, include_deleted=False)
        return [ReasonDTO.model_validate(x) for x in items]

    @staticmethod
    def list_reasons(
        uow,
        *,
        company_id: uuid.UUID,
        q: str | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> list[ReasonDTO]:
        items = uow.reasons.list(
            company_id=company_id,
            q=q,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        return [ReasonDTO.model_validate(x) for x in items]

    @staticmethod
    def get_reason(
        uow,
        *,
        company_id: uuid.UUID,
        reason_id: uuid.UUID,
    ) -> ReasonDTO:
        row = uow.reasons.get(company_id=company_id, reason_id=reason_id)
        if row is None:
            raise HTTPException(status_code=404, detail="reason not found")
        return ReasonDTO.model_validate(row)

    @staticmethod
    def create_reason(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        data: ReasonCreateDTO,
    ) -> ReasonDTO:
        try:
            row = ReasonsAdminService.create(
                uow,
                company_id=company_id,
                code=data.code,
                name=data.name,
                is_active=data.is_active,
            )
        except ReasonCodeAlreadyExists as e:
            raise HTTPException(status_code=409, detail=str(e))
        except IntegrityError as e:
            raise HTTPException(status_code=409, detail="reason code already exists") from e

        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="reason",
            entity_id=row.id,
            action="REASON_CREATE",
            before=None,
            after=_snapshot(row),
        )
        uow.session.flush()
        return ReasonDTO.model_validate(row)

    @staticmethod
    def import_reasons(
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

            existing = uow.reasons.get_by_code(
                company_id=company_id,
                code=code,
                include_deleted=True,
            )

            if existing is None:
                row = ReasonsAdminService.create(
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
                    entity_type="reason",
                    entity_id=row.id,
                    action="REASON_CREATE",
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
                uow.reasons.save(existing)
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="reason",
                    entity_id=existing.id,
                    action="REASON_UPDATE",
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
                detail="reason import conflicts with unique constraints",
            ) from e

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "skipped_existing": skipped_existing,
        }

    @staticmethod
    def bulk_reasons(
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
        for reason_id in unique_ids:
            row = uow.reasons.get(
                company_id=company_id,
                reason_id=reason_id,
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
                uow.reasons.save(row)
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="reason",
                    entity_id=row.id,
                    action="REASON_UPDATE",
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
                uow.reasons.save(row)
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="reason",
                    entity_id=row.id,
                    action="REASON_UPDATE",
                    reason="BULK_DEACTIVATE",
                    before=before,
                    after=_snapshot(row),
                )
                affected += 1
                continue

            if operation == "delete":
                ReasonsAdminService.delete(
                    uow,
                    company_id=company_id,
                    reason_id=row.id,
                )
                row_after = uow.reasons.get(
                    company_id=company_id,
                    reason_id=row.id,
                    include_deleted=True,
                )
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="reason",
                    entity_id=row.id,
                    action="REASON_DELETE",
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
    def update_reason(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        reason_id: uuid.UUID,
        data: ReasonUpdateDTO,
    ) -> ReasonDTO:
        existing = uow.reasons.get(company_id=company_id, reason_id=reason_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="reason not found")
        before = _snapshot(existing)

        try:
            row = ReasonsAdminService.update(
                uow,
                company_id=company_id,
                reason_id=reason_id,
                payload=data.model_dump(exclude_unset=True),
            )
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ReasonCodeAlreadyExists as e:
            raise HTTPException(status_code=409, detail=str(e))
        except IntegrityError as e:
            raise HTTPException(status_code=409, detail="reason code already exists") from e

        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="reason",
            entity_id=row.id,
            action="REASON_UPDATE",
            before=before,
            after=_snapshot(row),
        )
        uow.session.flush()
        return ReasonDTO.model_validate(row)

    @staticmethod
    def delete_reason(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        reason_id: uuid.UUID,
    ) -> None:
        row = uow.reasons.get(company_id=company_id, reason_id=reason_id)
        if row is None:
            raise HTTPException(status_code=404, detail="reason not found")
        before = _snapshot(row)
        ReasonsAdminService.delete(
            uow,
            company_id=company_id,
            reason_id=reason_id,
        )
        after_row = uow.reasons.get(
            company_id=company_id,
            reason_id=reason_id,
            include_deleted=True,
        )
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="reason",
            entity_id=reason_id,
            action="REASON_DELETE",
            before=before,
            after=_snapshot(after_row) if after_row else None,
        )
        uow.session.flush()
