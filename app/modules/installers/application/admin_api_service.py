from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.modules.installers.api.rates_schemas import (
    InstallerRateCreateDTO,
    InstallerRateDTO,
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
        svc = InstallersAdminService(uow.session)
        try:
            obj = svc.create(company_id, data)
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
            uow.commit()
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
        uow.commit()
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
    def create_rate(
        uow,
        *,
        company_id: uuid.UUID,
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
        uow.commit()
        return InstallerRateDTO.model_validate(obj)

    @staticmethod
    def update_rate(
        uow,
        *,
        company_id: uuid.UUID,
        rate_id: uuid.UUID,
        data: InstallerRateUpdateDTO,
    ) -> InstallerRateDTO:
        obj = uow.installer_rates.get(company_id, rate_id)
        if not obj:
            raise HTTPException(status_code=404, detail="installer rate not found")
        svc = RatesAdminService(uow.session)
        obj = svc.update(obj, data)
        uow.commit()
        return InstallerRateDTO.model_validate(obj)

    @staticmethod
    def delete_rate(
        uow,
        *,
        company_id: uuid.UUID,
        rate_id: uuid.UUID,
    ) -> None:
        obj = uow.installer_rates.get(company_id, rate_id)
        if not obj:
            raise HTTPException(status_code=404, detail="installer rate not found")
        svc = RatesAdminService(uow.session)
        svc.delete(obj)
        uow.commit()
