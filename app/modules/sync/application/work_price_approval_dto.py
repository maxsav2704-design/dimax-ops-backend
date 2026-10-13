from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.rates.application.approval_dto import Digest, PublicApproval


class IssueWorkPriceApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    factory_contact_id: UUID
    proposal_hash: Digest
    expires_in_hours: int = Field(default=72, ge=1, le=168, strict=True)


class WorkPriceApprovalSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    proposal_id: UUID
    factory_contact_id: UUID
    recipient_name: str
    recipient_email: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    confirmed_at: datetime | None
    confirmed_name: str | None
    mailbox_verified_at: datetime | None
    email_outbox_id: UUID
    affects_earnings: Literal[False] = False


class WorkPriceApprovalPage(BaseModel):
    items: list[WorkPriceApprovalSummary]
    total: int


class PublicWorkDetails(BaseModel):
    proposal_id: UUID
    project_name: str
    installer_name: str
    reference: str
    performed_at: datetime
    quantity: Decimal
    amount: Decimal


class PublicWorkPriceApproval(PublicApproval):
    work: PublicWorkDetails
