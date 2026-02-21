from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.installers.api.schemas import (
    InstallerCreateDTO,
    InstallerDTO,
    InstallerUpdateDTO,
    LinkUserDTO,
)
from app.modules.installers.application.admin_api_service import (
    InstallersAdminApiService,
)
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
        return InstallersAdminApiService.list_installers(
            uow,
            company_id=current_user.company_id,
            q=q,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )


@router.get("/{installer_id}", response_model=InstallerDTO)
def get_installer(
    installer_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerDTO:
    with uow:
        return InstallersAdminApiService.get_installer(
            uow,
            company_id=current_user.company_id,
            installer_id=installer_id,
        )


@router.post("", response_model=InstallerDTO, status_code=status.HTTP_201_CREATED)
def create_installer(
    data: InstallerCreateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerDTO:
    with uow:
        return InstallersAdminApiService.create_installer(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            data=data,
        )


@router.patch("/{installer_id}", response_model=InstallerDTO)
def update_installer(
    installer_id: uuid.UUID,
    data: InstallerUpdateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerDTO:
    with uow:
        return InstallersAdminApiService.update_installer(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            installer_id=installer_id,
            data=data,
        )


@router.delete("/{installer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_installer(
    installer_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    with uow:
        InstallersAdminApiService.delete_installer(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            installer_id=installer_id,
        )
    return None


@router.post("/{installer_id}/link-user", response_model=InstallerDTO)
def link_user(
    installer_id: uuid.UUID,
    data: LinkUserDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerDTO:
    with uow:
        return InstallersAdminApiService.link_user(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            installer_id=installer_id,
            user_id=data.user_id,
        )


@router.delete("/{installer_id}/link-user", response_model=InstallerDTO)
def unlink_user(
    installer_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerDTO:
    with uow:
        return InstallersAdminApiService.unlink_user(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            installer_id=installer_id,
        )
