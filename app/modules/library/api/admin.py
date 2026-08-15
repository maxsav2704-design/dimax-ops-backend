from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.library.api.schemas import (
    ProductLibraryCreateBody,
    ProductLibraryItemDTO,
    ProductLibraryListResponse,
    ProductLibraryUpdateBody,
)
from app.modules.library.application.admin_api_service import ProductLibraryAdminApiService


router = APIRouter(prefix="/admin/library", tags=["Admin / Product Library"])


@router.get("", response_model=ProductLibraryListResponse)
def list_library_items(
    q: str | None = Query(default=None, max_length=120),
    status_filter: str | None = Query(default=None, alias="status", pattern=r"^(ACTIVE|ARCHIVED)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
) -> ProductLibraryListResponse:
    with uow:
        return ProductLibraryListResponse(
            items=ProductLibraryAdminApiService.list_items(
                uow,
                company_id=current_user.company_id,
                q=q,
                status=status_filter,
                limit=limit,
                offset=offset,
            )
        )


@router.post("", response_model=ProductLibraryItemDTO, status_code=status.HTTP_201_CREATED)
def create_library_item(
    body: ProductLibraryCreateBody,
    current_user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
) -> ProductLibraryItemDTO:
    with uow:
        return ProductLibraryAdminApiService.create_item(
            uow,
            company_id=current_user.company_id,
            payload=body.model_dump(),
        )


@router.patch("/{item_id}", response_model=ProductLibraryItemDTO)
def update_library_item(
    item_id: uuid.UUID,
    body: ProductLibraryUpdateBody,
    current_user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
) -> ProductLibraryItemDTO:
    with uow:
        return ProductLibraryAdminApiService.update_item(
            uow,
            company_id=current_user.company_id,
            item_id=item_id,
            payload=body.model_dump(exclude_unset=True),
        )
