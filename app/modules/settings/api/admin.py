from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.settings.api.schemas import (
    CompanySettingsDTO,
    CompanySettingsUpdateDTO,
    CommunicationTemplateCreateDTO,
    CommunicationTemplateDTO,
    CommunicationTemplateRenderPreviewDTO,
    CommunicationTemplateRenderPreviewResponse,
    CommunicationTemplatesResponse,
    CommunicationTemplateUpdateDTO,
    IntegrationEmailTestSendDTO,
    IntegrationsHealthResponseDTO,
    IntegrationsSettingsDTO,
    IntegrationTestSendResponseDTO,
    IntegrationWhatsappTestSendDTO,
)
from app.modules.settings.application.admin_api_service import SettingsAdminApiService
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/settings", tags=["Admin / Settings"])


@router.get("/company", response_model=CompanySettingsDTO)
def get_company_settings(
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CompanySettingsDTO:
    with uow:
        return SettingsAdminApiService.get_company(
            uow,
            company_id=user.company_id,
        )


@router.patch("/company", response_model=CompanySettingsDTO)
def update_company_settings(
    body: CompanySettingsUpdateDTO,
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CompanySettingsDTO:
    with uow:
        return SettingsAdminApiService.update_company(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            data=body,
        )


@router.get("/integrations", response_model=IntegrationsSettingsDTO)
def get_integrations_settings(
    _user: CurrentUser = Depends(require_admin),
) -> IntegrationsSettingsDTO:
    return SettingsAdminApiService.get_integrations()


@router.get("/integrations/health", response_model=IntegrationsHealthResponseDTO)
def get_integrations_health(
    _user: CurrentUser = Depends(require_admin),
) -> IntegrationsHealthResponseDTO:
    return SettingsAdminApiService.get_integrations_health()


@router.post(
    "/integrations/test-email",
    response_model=IntegrationTestSendResponseDTO,
)
def send_test_email(
    body: IntegrationEmailTestSendDTO,
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> IntegrationTestSendResponseDTO:
    with uow:
        return SettingsAdminApiService.send_test_email(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            data=body,
        )


@router.post(
    "/integrations/test-whatsapp",
    response_model=IntegrationTestSendResponseDTO,
)
def send_test_whatsapp(
    body: IntegrationWhatsappTestSendDTO,
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> IntegrationTestSendResponseDTO:
    with uow:
        return SettingsAdminApiService.send_test_whatsapp(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            data=body,
        )


@router.get(
    "/communication-templates",
    response_model=CommunicationTemplatesResponse,
)
def list_communication_templates(
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CommunicationTemplatesResponse:
    with uow:
        return SettingsAdminApiService.list_templates(
            uow,
            company_id=user.company_id,
        )


@router.post(
    "/communication-templates",
    response_model=CommunicationTemplateDTO,
    status_code=201,
)
def create_communication_template(
    body: CommunicationTemplateCreateDTO,
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CommunicationTemplateDTO:
    with uow:
        return SettingsAdminApiService.create_template(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            data=body,
        )


@router.patch(
    "/communication-templates/{template_id}",
    response_model=CommunicationTemplateDTO,
)
def update_communication_template(
    template_id: UUID,
    body: CommunicationTemplateUpdateDTO,
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CommunicationTemplateDTO:
    with uow:
        return SettingsAdminApiService.update_template(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            template_id=template_id,
            data=body,
        )


@router.delete("/communication-templates/{template_id}", status_code=204)
def delete_communication_template(
    template_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> Response:
    with uow:
        SettingsAdminApiService.delete_template(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            template_id=template_id,
        )
        return Response(status_code=204)


@router.post(
    "/communication-templates/render-preview",
    response_model=CommunicationTemplateRenderPreviewResponse,
)
def render_communication_template_preview(
    body: CommunicationTemplateRenderPreviewDTO,
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CommunicationTemplateRenderPreviewResponse:
    with uow:
        return SettingsAdminApiService.render_template_preview(
            uow,
            company_id=user.company_id,
            data=body,
        )
