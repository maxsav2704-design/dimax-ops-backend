from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, field_validator

from app.modules.accounting.application.dto import CommercialPriceDetail, ContractTermsDetail, Reason
from app.modules.rates.application.approval_dto import Digest, Name, PreviewApproval
from app.modules.rates.application.contact_dto import FactoryContactView


class CommercialAgreement(BaseModel):
    company_id: UUID
    company_name: str
    contract_id: UUID
    contract_reference: str
    factory_name: str
    is_demo: bool
    terms: ContractTermsDetail
    price: CommercialPriceDetail


class ApprovalCandidate(BaseModel):
    snapshot: CommercialAgreement
    snapshot_hash: Digest
    contact: FactoryContactView | None


class IssueCommercialApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    terms_id: UUID
    price_id: UUID
    snapshot_hash: Digest
    factory_contact_id: UUID
    expires_in_hours: int = Field(default=72, ge=1, le=168, strict=True)


class RevokeCommercialApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason


class ConfirmCommercialApproval(PreviewApproval):
    terms_version: int = Field(gt=0, strict=True)
    price_version: int = Field(gt=0, strict=True)
    snapshot_hash: Digest
    signer_name: Name
    accepted: StrictBool
    verification_code: Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")]

    @field_validator("accepted")
    @classmethod
    def explicit_consent(cls, value):
        if not value:
            raise ValueError("Explicit confirmation of both versions is required")
        return value


class CommercialApprovalSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    contract_id: UUID
    terms_id: UUID
    price_id: UUID
    terms_version: int
    price_version: int
    factory_contact_id: UUID
    recipient_name: str
    recipient_email: str
    created_at: datetime
    expires_at: datetime
    confirmed_at: datetime | None
    confirmed_name: str | None
    revoked_at: datetime | None
    revocation_reason: str | None
    mailbox_verified_at: datetime | None
    snapshot_hash: str
    email_outbox_id: UUID
    delivery_status: str
    status: Literal["PENDING", "CONFIRMED", "REVOKED", "EXPIRED", "SUPERSEDED", "CONTACT_CHANGED"]
    is_demo: bool
    usable_for_billing: Literal[False] = False


class CommercialApprovalPage(BaseModel):
    items: list[CommercialApprovalSummary]
    total: int


class CommercialApprovalDetail(CommercialApprovalSummary):
    snapshot: CommercialAgreement


class PublicCommercialApproval(BaseModel):
    snapshot: CommercialAgreement
    snapshot_hash: Digest
    recipient_name: str
    expires_at: datetime
    status: Literal["PENDING", "CONFIRMED"]
    confirmed_at: datetime | None
    confirmed_name: str | None
    usable_for_billing: Literal[False] = False
