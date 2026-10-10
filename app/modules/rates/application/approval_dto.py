from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, StringConstraints, field_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
Token = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$", min_length=43, max_length=43)]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64)]


class IssueApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factory_name: Name
    recipient_name: Name
    recipient_email: EmailStr = Field(max_length=320)
    expires_in_hours: int = Field(default=72, ge=1, le=168, strict=True)
    send_email: StrictBool = False


class ApprovalSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    price_list_id: UUID
    factory_name: str
    recipient_name: str
    recipient_email: str
    created_by: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_by: UUID | None
    revocation_reason: str | None
    confirmed_at: datetime | None
    confirmed_name: str | None


class IssuedApproval(BaseModel):
    invitation: ApprovalSummary
    confirmation_url: str
    email_outbox_id: UUID | None = None


class ApprovalPage(BaseModel):
    items: list[ApprovalSummary]
    total: int


class PreviewApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: Token


class ConfirmApproval(PreviewApproval):
    expected_version: int = Field(gt=0, strict=True)
    snapshot_hash: Digest
    signer_name: Name
    accepted: StrictBool

    @field_validator("accepted")
    @classmethod
    def explicit_consent(cls, value):
        if not value:
            raise ValueError("Explicit price confirmation required")
        return value


class PublicApprovalLine(BaseModel):
    kind: Literal["DOOR", "ADDON"]
    name: str
    unit: str
    installer_price: Decimal


class PublicApproval(BaseModel):
    company_name: str
    factory_name: str
    recipient_name: str
    version: int
    currency: Literal["ILS"]
    reason: str
    agreement_reference: str
    items: list[PublicApprovalLine]
    snapshot_hash: str
    expires_at: datetime
    status: Literal["PENDING", "CONFIRMED"]
    confirmed_at: datetime | None
    confirmed_name: str | None
    affects_earnings: Literal[False] = False
