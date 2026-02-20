from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.installers.api.schemas import (
    InstallerCreateDTO,
    InstallerDTO,
    InstallerUpdateDTO,
    LinkUserDTO,
)
from app.modules.installers.application.admin_service import InstallersAdminService
from app.modules.installers.domain.errors import InvalidUserLink, UserAlreadyLinked
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/installers", tags=["Admin - Installers"])


@router.get("", response_model=list[InstallerDTO])
def list_installers(
    q: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> list[InstallerDTO]:
    with uow:
        items = uow.installers.list(
            company_id=current_user.company_id,
            q=q,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        return [InstallerDTO.model_validate(x) for x in items]


@router.get("/{installer_id}", response_model=InstallerDTO)
def get_installer(
    installer_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerDTO:
    with uow:
        obj = uow.installers.get(current_user.company_id, installer_id)
        if not obj or obj.deleted_at is not None:
            raise HTTPException(status_code=404, detail="installer not found")
        return InstallerDTO.model_validate(obj)


@router.post("", response_model=InstallerDTO, status_code=status.HTTP_201_CREATED)
def create_installer(
    data: InstallerCreateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerDTO:
    with uow:
        svc = InstallersAdminService(uow.session)
        try:
            obj = svc.create(current_user.company_id, data)
        except InvalidUserLink as e:
            raise HTTPException(status_code=400, detail=str(e))
        except IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail="installer violates unique constraints (e.g. phone)",
            ) from e
        return InstallerDTO.model_validate(obj)


@router.patch("/{installer_id}", response_model=InstallerDTO)
def update_installer(
    installer_id: uuid.UUID,
    data: InstallerUpdateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerDTO:
    with uow:
        obj = uow.installers.get(current_user.company_id, installer_id)
        if not obj or obj.deleted_at is not None:
            raise HTTPException(status_code=404, detail="installer not found")
        svc = InstallersAdminService(uow.session)
        try:
            obj = svc.update(current_user.company_id, obj, data)
        except InvalidUserLink as e:
            raise HTTPException(status_code=400, detail=str(e))
        except IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail="installer violates unique constraints (e.g. phone)",
            ) from e
        return InstallerDTO.model_validate(obj)


@router.delete("/{installer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_installer(
    installer_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    with uow:
        obj = uow.installers.get(current_user.company_id, installer_id)
        if not obj or obj.deleted_at is not None:
            raise HTTPException(status_code=404, detail="installer not found")
        svc = InstallersAdminService(uow.session)
        svc.soft_delete(obj)
    return None


@router.post("/{installer_id}/link-user", response_model=InstallerDTO)
def link_user(
    installer_id: uuid.UUID,
    data: LinkUserDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerDTO:
    try:
        with uow:
            obj = uow.installers.get(current_user.company_id, installer_id)
            if not obj or obj.deleted_at is not None:
                raise HTTPException(status_code=404, detail="installer not found")
            if obj.user_id == data.user_id:
                return InstallerDTO.model_validate(obj)  # idempotent: already linked
            svc = InstallersAdminService(uow.session)
            try:
                obj = svc.link_user(
                    current_user.company_id,
                    obj,
                    data.user_id,
                    get_installer_by_user_id_any=uow.installers.get_installer_by_user_id_any,
                )
            except InvalidUserLink as e:
                raise HTTPException(status_code=400, detail=str(e))
            except UserAlreadyLinked as e:
                raise HTTPException(status_code=409, detail=str(e))
            uow.commit()
            return InstallerDTO.model_validate(obj)
    except IntegrityError as e:
        # Race: два админа линкают одного user к разным installers → при commit срабатывает unique index
        raise HTTPException(
            status_code=409,
            detail="user already linked to another installer",
        ) from e


@router.delete("/{installer_id}/link-user", response_model=InstallerDTO)
def unlink_user(
    installer_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerDTO:
    with uow:
        obj = uow.installers.get(current_user.company_id, installer_id)
        if not obj or obj.deleted_at is not None:
            raise HTTPException(status_code=404, detail="installer not found")
        svc = InstallersAdminService(uow.session)
        obj = svc.unlink_user(obj)
        uow.commit()
        return InstallerDTO.model_validate(obj)
