from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class CompanySettingsDTO(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CompanySettingsUpdateDTO(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class IntegrationsSettingsDTO(BaseModel):
    public_base_url: str

    smtp_configured: bool
    email_enabled: bool
    twilio_configured: bool
    whatsapp_enabled: bool
    whatsapp_fallback_to_email: bool
    storage_configured: bool
    waze_base_url: str
    waze_navigation_enabled: bool

    file_token_ttl_sec: int
    file_token_uses: int
    journal_public_token_ttl_sec: int

    sync_warn_lag: int
    sync_danger_lag: int
    sync_warn_days_offline: int
    sync_danger_days_offline: int
    sync_project_auto_problem_enabled: bool
    sync_project_auto_problem_days: int

    auth_login_rl_window_sec: int
    auth_login_rl_max_req: int
    auth_refresh_rl_window_sec: int
    auth_refresh_rl_max_req: int


class CommunicationTemplateDTO(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    subject: str
    message: str
    send_email: bool
    send_whatsapp: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommunicationTemplatesResponse(BaseModel):
    items: list[CommunicationTemplateDTO]


class CommunicationTemplateCreateDTO(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    subject: str = Field(default="", max_length=200)
    message: str = Field(default="", max_length=4000)
    send_email: bool = True
    send_whatsapp: bool = True
    is_active: bool = True


class CommunicationTemplateUpdateDTO(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    subject: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=4000)
    send_email: bool | None = None
    send_whatsapp: bool | None = None
    is_active: bool | None = None


class CommunicationTemplateRenderPreviewDTO(BaseModel):
    template_id: uuid.UUID
    journal_id: uuid.UUID | None = None


class CommunicationTemplateRenderPreviewResponse(BaseModel):
    subject: str
    message: str
    variables: dict[str, str | None]


class IntegrationChannelHealthDTO(BaseModel):
    channel: str
    provider: str
    enabled: bool
    configured: bool
    ready: bool
    callback_configured: bool
    sender_identity: str | None = None
    fallback_enabled: bool | None = None
    validation_enabled: bool | None = None
    notes: list[str] = Field(default_factory=list)


class IntegrationsHealthResponseDTO(BaseModel):
    email: IntegrationChannelHealthDTO
    whatsapp: IntegrationChannelHealthDTO


class IntegrationEmailTestSendDTO(BaseModel):
    to_email: EmailStr
    subject: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=2000)


class IntegrationWhatsappTestSendDTO(BaseModel):
    to_phone: str = Field(min_length=7, max_length=30)
    message: str | None = Field(default=None, max_length=2000)


class IntegrationTestSendResponseDTO(BaseModel):
    ok: bool
    channel: str
    provider: str
    recipient: str
    provider_message_id: str | None = None
