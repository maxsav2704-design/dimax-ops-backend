from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.modules.installers.api.rates_schemas import (
    InstallerRateCreateDTO,
    InstallerRateDTO,
    InstallerRateTimelineResponse,
    InstallerRateUpdateDTO,
)
from app.modules.installers.api.schemas import (
    InstallerCreateDTO,
    InstallerDTO,
    InstallerUpdateDTO,
)
from app.modules.installers.application.admin_service import InstallersAdminService
from app.modules.installers.application.rates_admin_service import RatesAdminService
from app.modules.audit.application.service import AuditService
from app.modules.companies.application.alerts_service import CompanyLimitAlertsService
from app.modules.companies.application.limits_service import CompanyLimitsService
from app.modules.companies.domain.errors import CompanyPlanLimitExceeded
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.modules.installers.domain.errors import (
    DoorTypeNotFound,
    InstallerNotFound,
    InstallerRateAlreadyExists,
    InvalidUserLink,
    UserAlreadyLinked,
)


def _installer_snapshot(obj) -> dict:
    return {
        "full_name": obj.full_name,
        "phone": obj.phone,
        "status": obj.status,
        "is_active": obj.is_active,
        "user_id": str(obj.user_id) if obj.user_id else None,
        "deleted_at": obj.deleted_at.isoformat() if obj.deleted_at else None,
    }


def _installer_rate_snapshot(obj) -> dict:
    return {
        "installer_id": str(obj.installer_id),
        "door_type_id": str(obj.door_type_id),
        "price": str(obj.price),
        "effective_from": obj.effective_from.isoformat(),
    }


class InstallersAdminApiService:
    @staticmethod
    def list_installers(
        uow,
        *,
        company_id: uuid.UUID,
        q: str | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> list[InstallerDTO]:
        items = uow.installers.list(
            company_id=company_id,
            q=q,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        return [InstallerDTO.model_validate(x) for x in items]

    @staticmethod
    def get_installer(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> InstallerDTO:
        obj = uow.installers.get(company_id, installer_id)
        if not obj or obj.deleted_at is not None:
            raise HTTPException(status_code=404, detail="installer not found")
        return InstallerDTO.model_validate(obj)

    @staticmethod
    def create_installer(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        data: InstallerCreateDTO,
    ) -> InstallerDTO:
        try:
            CompanyLimitsService.assert_can_create_installer(uow, company_id=company_id)
            svc = InstallersAdminService(uow.session)
            obj = svc.create(company_id, data)
        except CompanyPlanLimitExceeded as e:
            AuditService.add_independent(
                company_id=company_id,
                actor_user_id=actor_user_id,
                entity_type="company_plan",
                entity_id=company_id,
                action="PLAN_LIMIT_BLOCK_INSTALLER_CREATE",
                before=e.details or None,
                after={"requested": "installer_create"},
            )
            raise HTTPException(status_code=409, detail=str(e))
        except InvalidUserLink as e:
            raise HTTPException(status_code=400, detail=str(e))
        except IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail="installer violates unique constraints (e.g. phone)",
            ) from e

        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="installer",
            entity_id=obj.id,
            action="INSTALLER_CREATE",
            before=None,
            after=_installer_snapshot(obj),
        )
        CompanyLimitAlertsService.evaluate_and_alert(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            metric_keys=["installers"],
        )
        return InstallerDTO.model_validate(obj)

    @staticmethod
    def update_installer(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        installer_id: uuid.UUID,
        data: InstallerUpdateDTO,
    ) -> InstallerDTO:
        obj = uow.installers.get(company_id, installer_id)
        if not obj or obj.deleted_at is not None:
            raise HTTPException(status_code=404, detail="installer not found")
        before = _installer_snapshot(obj)

        svc = InstallersAdminService(uow.session)
        try:
            obj = svc.update(company_id, obj, data)
        except InvalidUserLink as e:
            raise HTTPException(status_code=400, detail=str(e))
        except IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail="installer violates unique constraints (e.g. phone)",
            ) from e

        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="installer",
            entity_id=obj.id,
            action="INSTALLER_UPDATE",
            before=before,
            after=_installer_snapshot(obj),
        )
        return InstallerDTO.model_validate(obj)

    @staticmethod
    def delete_installer(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> None:
        obj = uow.installers.get(company_id, installer_id)
        if not obj or obj.deleted_at is not None:
            raise HTTPException(status_code=404, detail="installer not found")
        before = _installer_snapshot(obj)
        svc = InstallersAdminService(uow.session)
        svc.soft_delete(obj)
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="installer",
            entity_id=obj.id,
            action="INSTALLER_DELETE",
            before=before,
            after=_installer_snapshot(obj),
        )

    @staticmethod
    def link_user(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        installer_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> InstallerDTO:
        try:
            obj = uow.installers.get(company_id, installer_id)
            if not obj or obj.deleted_at is not None:
                raise HTTPException(status_code=404, detail="installer not found")
            if obj.user_id == user_id:
                return InstallerDTO.model_validate(obj)
            before = _installer_snapshot(obj)

            svc = InstallersAdminService(uow.session)
            try:
                obj = svc.link_user(
                    company_id,
                    obj,
                    user_id,
                    get_installer_by_user_id_any=uow.installers.get_installer_by_user_id_any,
                )
            except InvalidUserLink as e:
                raise HTTPException(status_code=400, detail=str(e))
            except UserAlreadyLinked as e:
                raise HTTPException(status_code=409, detail=str(e))

            AuditService.add(
                uow,
                company_id=company_id,
                actor_user_id=actor_user_id,
                entity_type="installer",
                entity_id=obj.id,
                action="INSTALLER_LINK_USER",
                before=before,
                after=_installer_snapshot(obj),
            )
            uow.session.flush()
            return InstallerDTO.model_validate(obj)
        except IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail="user already linked to another installer",
            ) from e

    @staticmethod
    def unlink_user(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> InstallerDTO:
        obj = uow.installers.get(company_id, installer_id)
        if not obj or obj.deleted_at is not None:
            raise HTTPException(status_code=404, detail="installer not found")
        before = _installer_snapshot(obj)
        svc = InstallersAdminService(uow.session)
        obj = svc.unlink_user(obj)
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="installer",
            entity_id=obj.id,
            action="INSTALLER_UNLINK_USER",
            before=before,
            after=_installer_snapshot(obj),
        )
        uow.session.flush()
        return InstallerDTO.model_validate(obj)


class InstallerRatesAdminApiService:
    @staticmethod
    def list_rates(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID | None,
        door_type_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> list[InstallerRateDTO]:
        items = uow.installer_rates.list(
            company_id=company_id,
            installer_id=installer_id,
            door_type_id=door_type_id,
            limit=limit,
            offset=offset,
        )
        return [InstallerRateDTO.model_validate(x) for x in items]

    @staticmethod
    def get_rate(
        uow,
        *,
        company_id: uuid.UUID,
        rate_id: uuid.UUID,
    ) -> InstallerRateDTO:
        obj = uow.installer_rates.get(company_id, rate_id)
        if not obj:
            raise HTTPException(status_code=404, detail="installer rate not found")
        return InstallerRateDTO.model_validate(obj)

    @staticmethod
    def rate_timeline(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        door_type_id: uuid.UUID,
        as_of: datetime | None,
    ) -> InstallerRateTimelineResponse:
        at = as_of or datetime.now(timezone.utc)
        versions = uow.installer_rates.list_by_scope(
            company_id=company_id,
            installer_id=installer_id,
            door_type_id=door_type_id,
        )
        effective = uow.installer_rates.get_by_keys(
            company_id=company_id,
            installer_id=installer_id,
            door_type_id=door_type_id,
            at=at,
        )
        return InstallerRateTimelineResponse(
            installer_id=installer_id,
            door_type_id=door_type_id,
            as_of=at,
            effective_rate=(
                InstallerRateDTO.model_validate(effective)
                if effective is not None
                else None
            ),
            versions=[InstallerRateDTO.model_validate(x) for x in versions],
        )

    @staticmethod
    def create_rate(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        data: InstallerRateCreateDTO,
    ) -> InstallerRateDTO:
        svc = RatesAdminService(uow.session)
        try:
            obj = svc.create(company_id, data)
        except InstallerNotFound as e:
            raise HTTPException(status_code=400, detail=str(e))
        except DoorTypeNotFound as e:
            raise HTTPException(status_code=400, detail=str(e))
        except InstallerRateAlreadyExists as e:
            raise HTTPException(status_code=409, detail=str(e))
        except IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail="installer rate violates unique constraints",
            ) from e
        uow.session.flush()
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="installer_rate",
            entity_id=obj.id,
            action="INSTALLER_RATE_CREATE",
            before=None,
            after=_installer_rate_snapshot(obj),
        )
        return InstallerRateDTO.model_validate(obj)

    @staticmethod
    def update_rate(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        rate_id: uuid.UUID,
        data: InstallerRateUpdateDTO,
    ) -> InstallerRateDTO:
        obj = uow.installer_rates.get(company_id, rate_id)
        if not obj:
            raise HTTPException(status_code=404, detail="installer rate not found")
        before = _installer_rate_snapshot(obj)
        svc = RatesAdminService(uow.session)
        try:
            obj = svc.update(obj, data)
        except IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail="installer rate violates unique constraints",
            ) from e
        uow.session.flush()
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="installer_rate",
            entity_id=obj.id,
            action="INSTALLER_RATE_UPDATE",
            before=before,
            after=_installer_rate_snapshot(obj),
        )
        return InstallerRateDTO.model_validate(obj)

    @staticmethod
    def delete_rate(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        rate_id: uuid.UUID,
    ) -> None:
        obj = uow.installer_rates.get(company_id, rate_id)
        if not obj:
            raise HTTPException(status_code=404, detail="installer rate not found")
        before = _installer_rate_snapshot(obj)
        svc = RatesAdminService(uow.session)
        svc.delete(obj)
        uow.session.flush()
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="installer_rate",
            entity_id=rate_id,
            action="INSTALLER_RATE_DELETE",
            before=before,
            after=None,
        )

    @staticmethod
    def bulk_rates(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        ids: list[uuid.UUID],
        operation: str,
        price: Decimal | None,
        effective_from: datetime | None,
    ) -> dict:
        if operation == "set_price" and price is None:
            raise HTTPException(status_code=422, detail="price is required for set_price")
        if operation == "delete" and price is not None:
            raise HTTPException(status_code=422, detail="price must be omitted for delete")
        if operation == "delete" and effective_from is not None:
            raise HTTPException(status_code=422, detail="effective_from must be omitted for delete")

        target_effective_from = (
            effective_from if effective_from is not None else datetime.now(timezone.utc)
        )

        affected = 0
        not_found = 0
        unchanged = 0

        unique_ids = list(dict.fromkeys(ids))
        svc = RatesAdminService(uow.session)

        for rate_id in unique_ids:
            obj = uow.installer_rates.get(company_id, rate_id)
            if not obj:
                not_found += 1
                continue

            before = _installer_rate_snapshot(obj)
            if operation == "set_price":
                existing = uow.installer_rates.get_by_scope_effective_from(
                    company_id=company_id,
                    installer_id=obj.installer_id,
                    door_type_id=obj.door_type_id,
                    effective_from=target_effective_from,
                )
                if existing is not None:
                    if existing.price == price:
                        unchanged += 1
                        continue
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "installer rate version already exists with "
                            "different price for effective_from"
                        ),
                    )

                new_version = InstallerRateORM(
                    company_id=company_id,
                    installer_id=obj.installer_id,
                    door_type_id=obj.door_type_id,
                    price=price,
                    effective_from=target_effective_from,
                )
                uow.session.add(new_version)
                uow.session.flush()
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="installer_rate",
                    entity_id=new_version.id,
                    action="INSTALLER_RATE_CREATE",
                    reason="BULK_SET_PRICE",
                    before=before,
                    after=_installer_rate_snapshot(new_version),
                )
                affected += 1
                continue

            if operation == "delete":
                svc.delete(obj)
                AuditService.add(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    entity_type="installer_rate",
                    entity_id=rate_id,
                    action="INSTALLER_RATE_DELETE",
                    reason="BULK_DELETE",
                    before=before,
                    after=None,
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
