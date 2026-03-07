from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.door_types.api.schemas import (
    DoorTypesBulkBody,
    DoorTypesBulkResponse,
    DoorTypeCreateDTO,
    DoorTypeDTO,
    DoorTypesExportResponse,
    DoorTypesImportBody,
    DoorTypesImportResponse,
    DoorTypeUpdateDTO,
)
from app.modules.door_types.application.admin_api_service import (
    DoorTypesAdminApiService,
)
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/door-types", tags=["Admin / Door Types"])


@router.get("/export", response_model=DoorTypesExportResponse)
def export_door_types(
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> DoorTypesExportResponse:
    with uow:
        return DoorTypesExportResponse(
            items=DoorTypesAdminApiService.export_door_types(
                uow,
                company_id=current_user.company_id,
            )
        )


@router.post("/import", response_model=DoorTypesImportResponse)
def import_door_types(
    body: DoorTypesImportBody,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> DoorTypesImportResponse:
    with uow:
        data = DoorTypesAdminApiService.import_door_types(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            items=[x.model_dump() for x in body.items],
            create_only=body.create_only,
        )
        return DoorTypesImportResponse(**data)


@router.post("/bulk", response_model=DoorTypesBulkResponse)
def bulk_door_types(
    body: DoorTypesBulkBody,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> DoorTypesBulkResponse:
    with uow:
        data = DoorTypesAdminApiService.bulk_door_types(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            ids=body.ids,
            operation=body.operation,
        )
        return DoorTypesBulkResponse(**data)


@router.get("", response_model=list[DoorTypeDTO])
def list_door_types(
    q: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> list[DoorTypeDTO]:
    with uow:
        return DoorTypesAdminApiService.list_door_types(
            uow,
            company_id=current_user.company_id,
            q=q,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )


@router.get("/{door_type_id}", response_model=DoorTypeDTO)
def get_door_type(
    door_type_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> DoorTypeDTO:
    with uow:
        return DoorTypesAdminApiService.get_door_type(
            uow,
            company_id=current_user.company_id,
            door_type_id=door_type_id,
        )


@router.post("", response_model=DoorTypeDTO, status_code=status.HTTP_201_CREATED)
def create_door_type(
    data: DoorTypeCreateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> DoorTypeDTO:
    with uow:
        return DoorTypesAdminApiService.create_door_type(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            data=data,
        )


@router.patch("/{door_type_id}", response_model=DoorTypeDTO)
def update_door_type(
    door_type_id: uuid.UUID,
    data: DoorTypeUpdateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> DoorTypeDTO:
    with uow:
        return DoorTypesAdminApiService.update_door_type(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            door_type_id=door_type_id,
            data=data,
        )


@router.delete("/{door_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_door_type(
    door_type_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    with uow:
        DoorTypesAdminApiService.delete_door_type(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            door_type_id=door_type_id,
        )
    return None
