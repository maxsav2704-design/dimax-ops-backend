from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.addons.api.admin_schemas import (
    AddonTypeDTO,
    AddonTypeListResponse,
    CreateAddonTypeBody,
    ProjectPlanResponse,
    SetProjectPlanBody,
)
from app.modules.addons.application.admin_api_service import AddonsAdminApiService


router = APIRouter(prefix="/admin/addons", tags=["Admin / Add-ons"])


@router.get("/types", response_model=AddonTypeListResponse)
def list_types(
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return AddonsAdminApiService.list_types(uow, company_id=user.company_id)


@router.post("/types", response_model=AddonTypeDTO)
def create_type(
    body: CreateAddonTypeBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return AddonsAdminApiService.create_type(
            uow,
            company_id=user.company_id,
            name=body.name,
            unit=body.unit,
            default_client_price=body.default_client_price,
            default_installer_price=body.default_installer_price,
        )


@router.put("/projects/{project_id}/plan", response_model=ProjectPlanResponse)
def set_plan(
    project_id: UUID,
    body: SetProjectPlanBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return AddonsAdminApiService.set_plan(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            addon_type_id=body.addon_type_id,
            qty_planned=body.qty_planned,
            client_price=body.client_price,
            installer_price=body.installer_price,
        )
