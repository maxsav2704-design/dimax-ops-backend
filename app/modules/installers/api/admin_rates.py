from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.installers.api.rates_schemas import (
    InstallerRateCreateDTO,
    InstallerRateDTO,
    InstallerRateUpdateDTO,
)
from app.modules.installers.application.rates_admin_service import RatesAdminService
from app.modules.installers.domain.errors import (
    DoorTypeNotFound,
    InstallerNotFound,
    InstallerRateAlreadyExists,
)
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/installer-rates", tags=["Admin - Installer Rates"])


@router.get("", response_model=list[InstallerRateDTO])
def list_installer_rates(
    installer_id: uuid.UUID | None = Query(default=None),
    door_type_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> list[InstallerRateDTO]:
    with uow:
        items = uow.installer_rates.list(
            company_id=current_user.company_id,
            installer_id=installer_id,
            door_type_id=door_type_id,
            limit=limit,
            offset=offset,
        )
        return [InstallerRateDTO.model_validate(x) for x in items]


@router.get("/{rate_id}", response_model=InstallerRateDTO)
def get_installer_rate(
    rate_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerRateDTO:
    with uow:
        obj = uow.installer_rates.get(current_user.company_id, rate_id)
        if not obj:
            raise HTTPException(status_code=404, detail="installer rate not found")
        return InstallerRateDTO.model_validate(obj)


@router.post("", response_model=InstallerRateDTO, status_code=status.HTTP_201_CREATED)
def create_installer_rate(
    data: InstallerRateCreateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerRateDTO:
    with uow:
        svc = RatesAdminService(uow.session)
        try:
            obj = svc.create(current_user.company_id, data)
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


@router.patch("/{rate_id}", response_model=InstallerRateDTO)
def update_installer_rate(
    rate_id: uuid.UUID,
    data: InstallerRateUpdateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerRateDTO:
    with uow:
        obj = uow.installer_rates.get(current_user.company_id, rate_id)
        if not obj:
            raise HTTPException(status_code=404, detail="installer rate not found")
        svc = RatesAdminService(uow.session)
        obj = svc.update(obj, data)
        uow.commit()
        return InstallerRateDTO.model_validate(obj)


@router.delete("/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_installer_rate(
    rate_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    with uow:
        obj = uow.installer_rates.get(current_user.company_id, rate_id)
        if not obj:
            raise HTTPException(status_code=404, detail="installer rate not found")
        svc = RatesAdminService(uow.session)
        svc.delete(obj)
        uow.commit()
    return None
