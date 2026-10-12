from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.rates.application.approval_dto import Name


class RegisterFactoryContact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_contact_id: UUID | None
    factory_name: Name
    recipient_name: Name
    recipient_email: EmailStr = Field(max_length=320)
    authority_reference: str = Field(min_length=3, max_length=500)


class FactoryContactView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    factory_name: str
    recipient_name: str
    recipient_email: str
    authority_reference: str
    approved_by: UUID
    created_at: datetime


class RevokeFactoryContact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_contact_id: UUID
    reason: str = Field(min_length=10, max_length=500)
