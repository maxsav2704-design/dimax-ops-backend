from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import get_uow, require_platform_token
from app.modules.companies.api.schemas import (
    PlatformCompanyCreateDTO,
    PlatformCompanyCreateResponseDTO,
    PlatformCompanyDTO,
    PlatformCompanyListResponseDTO,
    PlatformCompanyPlanDTO,
    PlatformCompanyPlanUpdateDTO,
    PlatformCompanyUserCreateDTO,
    PlatformCompanyUserDTO,
    PlatformCompanyStatusUpdateDTO,
    PlatformCompanyUsageDTO,
)
from app.modules.companies.application.platform_api_service import (
    CompaniesPlatformApiService,
)
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/platform/companies", tags=["Platform / Companies"])


@router.get("", response_model=PlatformCompanyListResponseDTO)
def list_companies(
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _platform=Depends(require_platform_token),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> PlatformCompanyListResponseDTO:
    with uow:
        return CompaniesPlatformApiService.list_companies(
            uow,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )


@router.post(
    "",
    response_model=PlatformCompanyCreateResponseDTO,
    status_code=status.HTTP_201_CREATED,
)
def create_company(
    body: PlatformCompanyCreateDTO,
    _platform=Depends(require_platform_token),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> PlatformCompanyCreateResponseDTO:
    with uow:
        return CompaniesPlatformApiService.create_company(uow, data=body)


@router.patch("/{company_id}/status", response_model=PlatformCompanyDTO)
def update_company_status(
    company_id: uuid.UUID,
    body: PlatformCompanyStatusUpdateDTO,
    _platform=Depends(require_platform_token),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> PlatformCompanyDTO:
    with uow:
        return CompaniesPlatformApiService.update_status(
            uow,
            company_id=company_id,
            is_active=body.is_active,
        )


@router.get("/{company_id}/plan", response_model=PlatformCompanyPlanDTO)
def get_company_plan(
    company_id: uuid.UUID,
    _platform=Depends(require_platform_token),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> PlatformCompanyPlanDTO:
    with uow:
        return CompaniesPlatformApiService.get_plan(uow, company_id=company_id)


@router.put("/{company_id}/plan", response_model=PlatformCompanyPlanDTO)
def update_company_plan(
    company_id: uuid.UUID,
    body: PlatformCompanyPlanUpdateDTO,
    _platform=Depends(require_platform_token),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> PlatformCompanyPlanDTO:
    with uow:
        return CompaniesPlatformApiService.update_plan(
            uow,
            company_id=company_id,
            data=body,
        )


@router.get("/{company_id}/usage", response_model=PlatformCompanyUsageDTO)
def get_company_usage(
    company_id: uuid.UUID,
    _platform=Depends(require_platform_token),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> PlatformCompanyUsageDTO:
    with uow:
        return CompaniesPlatformApiService.get_usage(uow, company_id=company_id)


@router.post("/{company_id}/users", response_model=PlatformCompanyUserDTO, status_code=status.HTTP_201_CREATED)
def create_company_user(
    company_id: uuid.UUID,
    body: PlatformCompanyUserCreateDTO,
    _platform=Depends(require_platform_token),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> PlatformCompanyUserDTO:
    with uow:
        return CompaniesPlatformApiService.create_user(
            uow,
            company_id=company_id,
            data=body,
        )
