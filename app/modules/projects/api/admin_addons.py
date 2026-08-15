from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import (
    CurrentUser,
    ensure_admin_can_view_rates,
    get_uow,
    require_admin,
)
from app.modules.projects.api.admin_addons_schemas import (
    CreateUrgencySurchargeBody,
    OkResponse,
    PlanBatchBody,
    PlanItemDTO,
    ProjectAddonPlanListResponse,
    ProjectAddonsResponse,
    UrgencySurchargeListResponse,
)
from app.modules.projects.application.admin_addons_service import (
    ProjectAdminAddonsService,
)

router = APIRouter(prefix="/admin/projects", tags=["Admin / Projects"])


@router.get("/{project_id}/addons", response_model=ProjectAddonsResponse)
def get_project_addons(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return ProjectAdminAddonsService.get_project_addons(
            uow,
            company_id=user.company_id,
            project_id=project_id,
        )


@router.get("/{project_id}/addons/plan", response_model=ProjectAddonPlanListResponse)
def get_project_addon_plan(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return ProjectAdminAddonsService.list_project_plan(
            uow,
            company_id=user.company_id,
            project_id=project_id,
        )


@router.post("/{project_id}/addons/plan", response_model=ProjectAddonPlanListResponse)
def upsert_plan_item(
    project_id: UUID,
    body: PlanItemDTO,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return ProjectAdminAddonsService.upsert_plan_item(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            item=body.model_dump(),
        )


@router.put("/{project_id}/addons/plan", response_model=ProjectAddonsResponse)
def upsert_plan_batch(
    project_id: UUID,
    body: PlanBatchBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return ProjectAdminAddonsService.upsert_plan_batch(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            items=[it.model_dump() for it in body.items],
        )


@router.delete(
    "/{project_id}/addons/plan/{addon_type_id}",
    response_model=OkResponse,
)
def delete_plan_item(
    project_id: UUID,
    addon_type_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return ProjectAdminAddonsService.delete_plan_item(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            addon_type_id=addon_type_id,
        )


@router.get(
    "/{project_id}/urgency-surcharges",
    response_model=UrgencySurchargeListResponse,
)
def get_urgency_surcharges(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return ProjectAdminAddonsService.list_urgency_surcharges(
            uow,
            company_id=user.company_id,
            project_id=project_id,
        )


@router.post(
    "/{project_id}/urgency-surcharges",
    response_model=UrgencySurchargeListResponse,
)
def create_urgency_surcharge(
    project_id: UUID,
    body: CreateUrgencySurchargeBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return ProjectAdminAddonsService.create_urgency_surcharge(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            body=body,
        )
