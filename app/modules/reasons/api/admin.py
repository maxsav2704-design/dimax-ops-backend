from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.reasons.api.schemas import (
    ReasonCreateDTO,
    ReasonDTO,
    ReasonsBulkBody,
    ReasonsBulkResponse,
    ReasonsExportResponse,
    ReasonsImportBody,
    ReasonsImportResponse,
    ReasonUpdateDTO,
)
from app.modules.reasons.application.admin_api_service import ReasonsAdminApiService
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/reasons", tags=["Admin / Reasons"])


@router.get("/export", response_model=ReasonsExportResponse)
def export_reasons(
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> ReasonsExportResponse:
    with uow:
        return ReasonsExportResponse(
            items=ReasonsAdminApiService.export_reasons(
                uow,
                company_id=current_user.company_id,
            )
        )


@router.post("/import", response_model=ReasonsImportResponse)
def import_reasons(
    body: ReasonsImportBody,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> ReasonsImportResponse:
    with uow:
        data = ReasonsAdminApiService.import_reasons(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            items=[x.model_dump() for x in body.items],
            create_only=body.create_only,
        )
        return ReasonsImportResponse(**data)


@router.post("/bulk", response_model=ReasonsBulkResponse)
def bulk_reasons(
    body: ReasonsBulkBody,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> ReasonsBulkResponse:
    with uow:
        data = ReasonsAdminApiService.bulk_reasons(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            ids=body.ids,
            operation=body.operation,
        )
        return ReasonsBulkResponse(**data)


@router.get("", response_model=list[ReasonDTO])
def list_reasons(
    q: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> list[ReasonDTO]:
    with uow:
        return ReasonsAdminApiService.list_reasons(
            uow,
            company_id=current_user.company_id,
            q=q,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )


@router.get("/{reason_id}", response_model=ReasonDTO)
def get_reason(
    reason_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> ReasonDTO:
    with uow:
        return ReasonsAdminApiService.get_reason(
            uow,
            company_id=current_user.company_id,
            reason_id=reason_id,
        )


@router.post("", response_model=ReasonDTO, status_code=status.HTTP_201_CREATED)
def create_reason(
    data: ReasonCreateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> ReasonDTO:
    with uow:
        return ReasonsAdminApiService.create_reason(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            data=data,
        )


@router.patch("/{reason_id}", response_model=ReasonDTO)
def update_reason(
    reason_id: uuid.UUID,
    data: ReasonUpdateDTO,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> ReasonDTO:
    with uow:
        return ReasonsAdminApiService.update_reason(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            reason_id=reason_id,
            data=data,
        )


@router.delete("/{reason_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reason(
    reason_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    with uow:
        ReasonsAdminApiService.delete_reason(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            reason_id=reason_id,
        )
    return None
