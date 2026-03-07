from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.modules.companies.api.schemas import (
    PlatformCompanyCreateDTO,
    PlatformCompanyCreateResponseDTO,
    PlatformCompanyDTO,
    PlatformCompanyListResponseDTO,
    PlatformCompanyPlanDTO,
    PlatformCompanyPlanUpdateDTO,
    PlatformCompanyUserCreateDTO,
    PlatformCompanyUserDTO,
    PlatformCompanyUsageDTO,
)
from app.modules.companies.application.service import CompaniesPlatformService
from app.modules.companies.domain.errors import (
    CompanyAlreadyExists,
    CompanyNotFound,
    CompanyPlanLimitExceeded,
)
from app.shared.domain.errors import ValidationError


class CompaniesPlatformApiService:
    @staticmethod
    def list_companies(
        uow,
        *,
        include_inactive: bool,
        limit: int,
        offset: int,
    ) -> PlatformCompanyListResponseDTO:
        items, total = CompaniesPlatformService.list_companies(
            uow,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
        return PlatformCompanyListResponseDTO(
            items=[PlatformCompanyDTO.model_validate(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def create_company(
        uow,
        *,
        data: PlatformCompanyCreateDTO,
    ) -> PlatformCompanyCreateResponseDTO:
        try:
            company, admin, _plan = CompaniesPlatformService.create_company_with_admin(
                uow,
                data=data,
            )
        except CompanyAlreadyExists as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        return PlatformCompanyCreateResponseDTO(
            company=PlatformCompanyDTO.model_validate(company),
            admin_user_id=admin.id,
        )

    @staticmethod
    def update_status(
        uow,
        *,
        company_id: uuid.UUID,
        is_active: bool,
    ) -> PlatformCompanyDTO:
        try:
            company = CompaniesPlatformService.update_company_status(
                uow,
                company_id=company_id,
                is_active=is_active,
            )
        except CompanyNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        uow.session.flush()
        return PlatformCompanyDTO.model_validate(company)

    @staticmethod
    def get_plan(
        uow,
        *,
        company_id: uuid.UUID,
    ) -> PlatformCompanyPlanDTO:
        try:
            plan = CompaniesPlatformService.get_company_plan(uow, company_id=company_id)
        except CompanyNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return PlatformCompanyPlanDTO.model_validate(plan)

    @staticmethod
    def update_plan(
        uow,
        *,
        company_id: uuid.UUID,
        data: PlatformCompanyPlanUpdateDTO,
    ) -> PlatformCompanyPlanDTO:
        try:
            plan = CompaniesPlatformService.update_company_plan(
                uow,
                company_id=company_id,
                data=data,
            )
        except CompanyNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        uow.session.flush()
        return PlatformCompanyPlanDTO.model_validate(plan)

    @staticmethod
    def create_user(
        uow,
        *,
        company_id: uuid.UUID,
        data: PlatformCompanyUserCreateDTO,
    ) -> PlatformCompanyUserDTO:
        try:
            user = CompaniesPlatformService.create_company_user(
                uow,
                company_id=company_id,
                data=data,
            )
        except CompanyNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except CompanyPlanLimitExceeded as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="User email already exists") from exc
        return PlatformCompanyUserDTO.model_validate(user)

    @staticmethod
    def get_usage(
        uow,
        *,
        company_id: uuid.UUID,
    ) -> PlatformCompanyUsageDTO:
        try:
            usage = CompaniesPlatformService.get_company_usage(
                uow,
                company_id=company_id,
            )
        except CompanyNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return PlatformCompanyUsageDTO(**usage)
