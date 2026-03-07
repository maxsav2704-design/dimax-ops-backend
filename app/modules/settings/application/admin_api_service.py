from __future__ import annotations

import uuid

from fastapi import HTTPException

from app.modules.audit.application.service import AuditService
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
from app.modules.settings.application.admin_service import SettingsAdminService
from app.shared.domain.errors import DomainError, NotFound


def _snapshot_company(obj) -> dict:
    return {"name": obj.name, "is_active": obj.is_active}


class SettingsAdminApiService:
    @staticmethod
    def get_company(
        uow,
        *,
        company_id: uuid.UUID,
    ) -> CompanySettingsDTO:
        try:
            row = SettingsAdminService.get_company(uow, company_id=company_id)
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        return CompanySettingsDTO.model_validate(row)

    @staticmethod
    def update_company(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        data: CompanySettingsUpdateDTO,
    ) -> CompanySettingsDTO:
        try:
            row = SettingsAdminService.get_company(uow, company_id=company_id)
        except NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        before = _snapshot_company(row)

        row = SettingsAdminService.update_company(
            uow,
            company_id=company_id,
            name=data.name,
        )

        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="company",
            entity_id=row.id,
            action="SETTINGS_COMPANY_UPDATE",
            before=before,
            after=_snapshot_company(row),
        )
        uow.session.flush()
        return CompanySettingsDTO.model_validate(row)

    @staticmethod
    def get_integrations() -> IntegrationsSettingsDTO:
        data = SettingsAdminService.get_integrations()
        return IntegrationsSettingsDTO(**data)

    @staticmethod
    def get_integrations_health() -> IntegrationsHealthResponseDTO:
        return IntegrationsHealthResponseDTO(**SettingsAdminService.get_integrations_health())

    @staticmethod
    def list_templates(
        uow,
        *,
        company_id: uuid.UUID,
    ) -> CommunicationTemplatesResponse:
        rows = SettingsAdminService.list_templates(uow, company_id=company_id)
        return CommunicationTemplatesResponse(
            items=[CommunicationTemplateDTO.model_validate(row) for row in rows]
        )

    @staticmethod
    def create_template(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        data: CommunicationTemplateCreateDTO,
    ) -> CommunicationTemplateDTO:
        row = SettingsAdminService.create_template(
            uow,
            company_id=company_id,
            name=data.name,
            subject=data.subject,
            message=data.message,
            send_email=data.send_email,
            send_whatsapp=data.send_whatsapp,
            is_active=data.is_active,
        )
        uow.session.flush()
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="communication_template",
            entity_id=row.id,
            action="COMMUNICATION_TEMPLATE_CREATE",
            after={
                "code": row.code,
                "name": row.name,
                "subject": row.subject,
                "message": row.message,
                "send_email": row.send_email,
                "send_whatsapp": row.send_whatsapp,
                "is_active": row.is_active,
            },
        )
        return CommunicationTemplateDTO.model_validate(row)

    @staticmethod
    def update_template(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        template_id: uuid.UUID,
        data: CommunicationTemplateUpdateDTO,
    ) -> CommunicationTemplateDTO:
        before_row = SettingsAdminService.get_template(
            uow,
            company_id=company_id,
            template_id=template_id,
        )
        before = {
            "code": before_row.code,
            "name": before_row.name,
            "subject": before_row.subject,
            "message": before_row.message,
            "send_email": before_row.send_email,
            "send_whatsapp": before_row.send_whatsapp,
            "is_active": before_row.is_active,
        }
        row = SettingsAdminService.update_template(
            uow,
            company_id=company_id,
            template_id=template_id,
            name=data.name,
            subject=data.subject,
            message=data.message,
            send_email=data.send_email,
            send_whatsapp=data.send_whatsapp,
            is_active=data.is_active,
        )
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="communication_template",
            entity_id=row.id,
            action="COMMUNICATION_TEMPLATE_UPDATE",
            before=before,
            after={
                "code": row.code,
                "name": row.name,
                "subject": row.subject,
                "message": row.message,
                "send_email": row.send_email,
                "send_whatsapp": row.send_whatsapp,
                "is_active": row.is_active,
            },
        )
        uow.session.flush()
        return CommunicationTemplateDTO.model_validate(row)

    @staticmethod
    def delete_template(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        template_id: uuid.UUID,
    ) -> None:
        row = SettingsAdminService.get_template(
            uow,
            company_id=company_id,
            template_id=template_id,
        )
        before = {
            "code": row.code,
            "name": row.name,
            "subject": row.subject,
            "message": row.message,
            "send_email": row.send_email,
            "send_whatsapp": row.send_whatsapp,
            "is_active": row.is_active,
        }
        SettingsAdminService.delete_template(
            uow,
            company_id=company_id,
            template_id=template_id,
        )
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="communication_template",
            entity_id=template_id,
            action="COMMUNICATION_TEMPLATE_DELETE",
            before=before,
        )

    @staticmethod
    def render_template_preview(
        uow,
        *,
        company_id: uuid.UUID,
        data: CommunicationTemplateRenderPreviewDTO,
    ) -> CommunicationTemplateRenderPreviewResponse:
        _, variables, subject, message = SettingsAdminService.render_template_preview(
            uow,
            company_id=company_id,
            template_id=data.template_id,
            journal_id=data.journal_id,
        )
        return CommunicationTemplateRenderPreviewResponse(
            subject=subject,
            message=message,
            variables=variables,
        )

    @staticmethod
    def send_test_email(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        data: IntegrationEmailTestSendDTO,
    ) -> IntegrationTestSendResponseDTO:
        try:
            SettingsAdminService.send_test_email(
                to_email=str(data.to_email),
                subject=data.subject,
                message=data.message,
            )
        except DomainError:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"SMTP test send failed: {e}") from e
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="integration_channel",
            entity_id=company_id,
            action="INTEGRATION_TEST_EMAIL_SEND",
            after={
                "channel": "EMAIL",
                "provider": "SMTP",
                "recipient": str(data.to_email),
            },
        )
        return IntegrationTestSendResponseDTO(
            ok=True,
            channel="EMAIL",
            provider="SMTP",
            recipient=str(data.to_email),
            provider_message_id=None,
        )

    @staticmethod
    def send_test_whatsapp(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        data: IntegrationWhatsappTestSendDTO,
    ) -> IntegrationTestSendResponseDTO:
        try:
            provider_message_id = SettingsAdminService.send_test_whatsapp(
                to_phone=data.to_phone,
                message=data.message,
            )
        except DomainError:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"WhatsApp test send failed: {e}",
            ) from e
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="integration_channel",
            entity_id=company_id,
            action="INTEGRATION_TEST_WHATSAPP_SEND",
            after={
                "channel": "WHATSAPP",
                "provider": "TWILIO",
                "recipient": data.to_phone,
                "provider_message_id": provider_message_id,
            },
        )
        return IntegrationTestSendResponseDTO(
            ok=True,
            channel="WHATSAPP",
            provider="TWILIO",
            recipient=data.to_phone,
            provider_message_id=provider_message_id,
        )
