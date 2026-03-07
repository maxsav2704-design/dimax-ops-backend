from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.installers.api.rates_schemas import (
    InstallerRatesBulkBody,
    InstallerRatesBulkResponse,
    InstallerRateCreateDTO,
    InstallerRateDTO,
    InstallerRateTimelineResponse,
    InstallerRateUpdateDTO,
)
from app.modules.installers.application.admin_api_service import (
    InstallerRatesAdminApiService,
)
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/installer-rates", tags=["Admin - Installer Rates"])


@router.get("/timeline", response_model=InstallerRateTimelineResponse)
def get_installer_rate_timeline(
    installer_id: uuid.UUID = Query(),
    door_type_id: uuid.UUID = Query(),
    as_of: datetime | None = Query(default=None),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerRateTimelineResponse:
    if as_of is not None and (
        as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None
    ):
        raise HTTPException(status_code=422, detail="as_of must include timezone")
    with uow:
        return InstallerRatesAdminApiService.rate_timeline(
            uow,
            company_id=current_user.company_id,
            installer_id=installer_id,
            door_type_id=door_type_id,
            as_of=as_of,
        )


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
        return InstallerRatesAdminApiService.list_rates(
            uow,
            company_id=current_user.company_id,
            installer_id=installer_id,
            door_type_id=door_type_id,
            limit=limit,
            offset=offset,
        )


@router.get("/{rate_id}", response_model=InstallerRateDTO)
def get_installer_rate(
    rate_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerRateDTO:
    with uow:
        return InstallerRatesAdminApiService.get_rate(
            uow,
            company_id=current_user.company_id,
            rate_id=rate_id,
        )


@router.post("", response_model=InstallerRateDTO, status_code=status.HTTP_201_CREATED)
def create_installer_rate(
    data: InstallerRateCreateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerRateDTO:
    with uow:
        return InstallerRatesAdminApiService.create_rate(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            data=data,
        )


@router.patch("/{rate_id}", response_model=InstallerRateDTO)
def update_installer_rate(
    rate_id: uuid.UUID,
    data: InstallerRateUpdateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerRateDTO:
    with uow:
        return InstallerRatesAdminApiService.update_rate(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            rate_id=rate_id,
            data=data,
        )


@router.post("/bulk", response_model=InstallerRatesBulkResponse)
def bulk_installer_rates(
    body: InstallerRatesBulkBody,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> InstallerRatesBulkResponse:
    with uow:
        data = InstallerRatesAdminApiService.bulk_rates(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            ids=body.ids,
            operation=body.operation,
            price=body.price,
            effective_from=body.effective_from,
        )
    return InstallerRatesBulkResponse(**data)


@router.delete("/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_installer_rate(
    rate_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    with uow:
        InstallerRatesAdminApiService.delete_rate(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            rate_id=rate_id,
        )
    return None
