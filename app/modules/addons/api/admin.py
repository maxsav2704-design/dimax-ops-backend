from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.addons.api.admin_schemas import (
    AddonTypeDTO,
    AddonTypeListResponse,
    CreateAddonTypeBody,
    ProjectPlanItemDTO,
    ProjectPlanResponse,
    SetProjectPlanBody,
)
from app.modules.addons.application.use_cases import AddonsUseCases


router = APIRouter(prefix="/admin/addons", tags=["Admin / Add-ons"])


@router.get("/types", response_model=AddonTypeListResponse)
def list_types(
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        rows = uow.addon_types.list_active(company_id=user.company_id)
        return AddonTypeListResponse(
            items=[
                AddonTypeDTO(
                    id=r.id,
                    name=r.name,
                    unit=r.unit,
                    default_client_price=r.default_client_price,
                    default_installer_price=r.default_installer_price,
                    is_active=r.is_active,
                )
                for r in rows
            ]
        )


@router.post("/types", response_model=AddonTypeDTO)
def create_type(
    body: CreateAddonTypeBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        r = AddonsUseCases.admin_create_addon_type(
            uow,
            company_id=user.company_id,
            name=body.name,
            unit=body.unit,
            default_client_price=body.default_client_price,
            default_installer_price=body.default_installer_price,
        )
        return AddonTypeDTO(
            id=r.id,
            name=r.name,
            unit=r.unit,
            default_client_price=r.default_client_price,
            default_installer_price=r.default_installer_price,
            is_active=r.is_active,
        )


@router.put("/projects/{project_id}/plan", response_model=ProjectPlanResponse)
def set_plan(
    project_id: UUID,
    body: SetProjectPlanBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        AddonsUseCases.admin_set_project_plan(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            addon_type_id=body.addon_type_id,
            qty_planned=body.qty_planned,
            client_price=body.client_price,
            installer_price=body.installer_price,
        )
        rows = uow.addon_plans.list_by_project(
            company_id=user.company_id, project_id=project_id
        )
        return ProjectPlanResponse(
            project_id=project_id,
            items=[
                ProjectPlanItemDTO(
                    addon_type_id=x.addon_type_id,
                    qty_planned=x.qty_planned,
                    client_price=x.client_price,
                    installer_price=x.installer_price,
                )
                for x in rows
            ],
        )
