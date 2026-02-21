from __future__ import annotations

import uuid
from decimal import Decimal

from app.modules.addons.application.use_cases import AddonsUseCases
from app.modules.projects.api.admin_addons_schemas import (
    AddonTypeMini,
    AddonsSummaryItem,
    FactItemDTO,
    OkResponse,
    PlanItemDTO,
    ProjectAddonsResponse,
)
from app.shared.domain.errors import NotFound


class ProjectAdminAddonsService:
    @staticmethod
    def _build_project_addons_response(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> ProjectAddonsResponse:
        p = uow.projects.get(company_id=company_id, project_id=project_id)
        if not p:
            raise NotFound("Project not found")

        types = uow.addon_types.list_active(company_id=company_id)
        plan = uow.addon_plans.list_by_project(
            company_id=company_id, project_id=project_id
        )
        facts = uow.addon_facts.list_by_project_all(
            company_id=company_id, project_id=project_id
        )

        plan_map = {x.addon_type_id: x for x in plan}

        done_qty: dict[uuid.UUID, Decimal] = {}
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

    @staticmethod
    def get_project_addons(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> ProjectAddonsResponse:
        return ProjectAdminAddonsService._build_project_addons_response(
            uow,
            company_id=company_id,
            project_id=project_id,
        )

    @staticmethod
    def upsert_plan_batch(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        items: list[dict],
    ) -> ProjectAddonsResponse:
        AddonsUseCases.admin_set_project_plan_batch(
            uow,
            company_id=company_id,
            project_id=project_id,
            items=items,
        )
        return ProjectAdminAddonsService._build_project_addons_response(
            uow,
            company_id=company_id,
            project_id=project_id,
        )

    @staticmethod
    def delete_plan_item(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        addon_type_id: uuid.UUID,
    ) -> OkResponse:
        AddonsUseCases.admin_delete_project_plan_item(
            uow,
            company_id=company_id,
            project_id=project_id,
            addon_type_id=addon_type_id,
        )
        return OkResponse()
