from __future__ import annotations

import uuid

from app.modules.addons.api.admin_schemas import (
    AddonTypeDTO,
    AddonTypeListResponse,
    ProjectPlanItemDTO,
    ProjectPlanResponse,
)
from app.modules.addons.application.use_cases import AddonsUseCases


class AddonsAdminApiService:
    @staticmethod
    def list_types(uow, *, company_id: uuid.UUID) -> AddonTypeListResponse:
        rows = uow.addon_types.list_active(company_id=company_id)
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

    @staticmethod
    def create_type(
        uow,
        *,
        company_id: uuid.UUID,
        name: str,
        unit: str,
        default_client_price,
        default_installer_price,
    ) -> AddonTypeDTO:
        r = AddonsUseCases.admin_create_addon_type(
            uow,
            company_id=company_id,
            name=name,
            unit=unit,
            default_client_price=default_client_price,
            default_installer_price=default_installer_price,
        )
        uow.session.flush()
        return AddonTypeDTO(
            id=r.id,
            name=r.name,
            unit=r.unit,
            default_client_price=r.default_client_price,
            default_installer_price=r.default_installer_price,
            is_active=r.is_active,
        )

    @staticmethod
    def set_plan(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        addon_type_id: uuid.UUID,
        qty_planned,
        client_price,
        installer_price,
    ) -> ProjectPlanResponse:
        AddonsUseCases.admin_set_project_plan(
            uow,
            company_id=company_id,
            project_id=project_id,
            addon_type_id=addon_type_id,
            qty_planned=qty_planned,
            client_price=client_price,
            installer_price=installer_price,
        )
        uow.session.flush()
        rows = uow.addon_plans.list_by_project(
            company_id=company_id, project_id=project_id
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
