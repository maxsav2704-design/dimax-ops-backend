from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class InstallerJournalSummary(BaseModel):
    id: UUID
    project_id: UUID
    project_name: str
    project_address: str | None
    developer_company: str | None
    developer_email: str | None
    status: str
    completed_doors: int
    completed_addons: int
    signed_at: datetime | None
    signer_name: str | None
    email_delivery_status: str
    email_last_error: str | None
    can_submit: bool


class InstallerJournalListResponse(BaseModel):
    items: list[InstallerJournalSummary]


class InstallerJournalPrepareBody(BaseModel):
    project_id: UUID


class InstallerJournalDoorItem(BaseModel):
    unit_label: str
    door_type_name: str
    installed_at: datetime | None


class InstallerJournalAddonItem(BaseModel):
    name: str
    quantity: str
    unit: str
    done_at: datetime
    comment: str | None


class InstallerJournalDetailsResponse(InstallerJournalSummary):
    title: str | None
    snapshot_version: int
    public_token_expires_at: datetime | None
    signing_url: str | None
    doors: list[InstallerJournalDoorItem]
    addon_items: list[InstallerJournalAddonItem]


class InstallerJournalMarkReadyResponse(BaseModel):
    signing_url: str
    public_token_expires_at: datetime


class InstallerJournalPdfLinkResponse(BaseModel):
    url: str
    ttl_sec: int
    uses: int
