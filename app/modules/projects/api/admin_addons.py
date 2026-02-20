from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.addons.application.use_cases import AddonsUseCases
from app.shared.domain.errors import NotFound
from app.modules.projects.api.admin_addons_schemas import (
    AddonTypeMini,
    AddonsSummaryItem,
    FactItemDTO,
    PlanBatchBody,
    PlanItemDTO,
    ProjectAddonsResponse,
)

router = APIRouter(prefix="/admin/projects", tags=["Admin / Projects"])


def _build_project_addons_response(project_id: UUID, user: CurrentUser, uow):
    p = uow.projects.get(company_id=user.company_id, project_id=project_id)
    if not p:
        raise NotFound("Project not found")

    types = uow.addon_types.list_active(company_id=user.company_id)
    plan = uow.addon_plans.list_by_project(
        company_id=user.company_id, project_id=project_id
    )
    facts = uow.addon_facts.list_by_project_all(
        company_id=user.company_id, project_id=project_id
    )

    plan_map = {x.addon_type_id: x for x in plan}

    done_qty: dict[UUID, Decimal] = {}
    for f in facts:
        done_qty[f.addon_type_id] = (
            done_qty.get(f.addon_type_id, Decimal("0")) + f.qty_done
        )

    summary: list[AddonsSummaryItem] = []
    all_type_ids = set(done_qty.keys()) | set(plan_map.keys())
    for addon_type_id in all_type_ids:
        q_done = done_qty.get(addon_type_id, Decimal("0"))
        pl = plan_map.get(addon_type_id)
        if pl:
            revenue = q_done * pl.client_price
            payroll = q_done * pl.installer_price
            profit = revenue - payroll
            missing = False
            q_planned = pl.qty_planned
        else:
            revenue = Decimal("0")
            payroll = Decimal("0")
            profit = Decimal("0")
            missing = q_done > 0
            q_planned = Decimal("0")

        summary.append(
            AddonsSummaryItem(
                addon_type_id=addon_type_id,
                qty_planned=q_planned,
                qty_done=q_done,
                revenue=revenue,
                payroll=payroll,
                profit=profit,
                missing_plan=missing,
            )
        )

    return ProjectAddonsResponse(
        project_id=project_id,
        types=[
            AddonTypeMini(
                id=t.id,
                name=t.name,
                unit=t.unit,
                default_client_price=t.default_client_price,
                default_installer_price=t.default_installer_price,
            )
            for t in types
        ],
        plan=[
            PlanItemDTO(
                addon_type_id=x.addon_type_id,
                qty_planned=x.qty_planned,
                client_price=x.client_price,
                installer_price=x.installer_price,
            )
            for x in plan
        ],
        facts=[
            FactItemDTO(
                id=f.id,
                addon_type_id=f.addon_type_id,
                installer_id=f.installer_id,
                qty_done=f.qty_done,
                done_at=f.done_at,
                comment=f.comment,
                source=str(f.source),
            )
            for f in facts
        ],
        summary=summary,
    )


@router.get("/{project_id}/addons", response_model=ProjectAddonsResponse)
def get_project_addons(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return _build_project_addons_response(project_id, user, uow)


@router.put("/{project_id}/addons/plan", response_model=ProjectAddonsResponse)
def upsert_plan_batch(
    project_id: UUID,
    body: PlanBatchBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        AddonsUseCases.admin_set_project_plan_batch(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            items=[it.model_dump() for it in body.items],
        )
        return _build_project_addons_response(project_id, user, uow)


@router.delete("/{project_id}/addons/plan/{addon_type_id}")
def delete_plan_item(
    project_id: UUID,
    addon_type_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        AddonsUseCases.admin_delete_project_plan_item(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            addon_type_id=addon_type_id,
        )
        return {"ok": True}
