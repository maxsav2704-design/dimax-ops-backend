from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ReconciliationLine(BaseModel):
    kind: Literal["DOOR", "ADDON"]
    target_id: UUID
    name: str
    unit: str
    proposed_name: str | None
    proposed_unit: str | None
    source_type: Literal["INSTALLER_RATE", "SCHEDULED_RATE", "DOOR", "ADDON_PLAN", "ADDON_DEFAULT", "ADDON_FACT", "CATALOG"]
    source_id: UUID
    source_name: str | None
    project_id: UUID | None
    project_name: str | None
    installer_id: UUID | None
    installer_name: str | None
    effective_from: datetime | None
    quantity: Decimal | None
    legacy_price: Decimal | None
    legacy_variants: int
    proposed_price: Decimal | None
    delta: Decimal | None
    uses_snapshot: bool
    uses_surcharge: bool
    catalog_changed: bool
    source_available: bool
    review_required: bool
    status: Literal["MATCH", "DIFFERENT", "MISSING_PROPOSED", "MISSING_LEGACY", "UNAVAILABLE", "UNIT_CHANGED"]


class ReconciliationSummary(BaseModel):
    total_sources: int
    review_sources: int
    matching: int
    different: int
    missing_proposed: int
    missing_legacy: int
    unavailable: int
    unit_changed: int
    scheduled_rates: int
    door_snapshots: int
    door_surcharges: int
    catalog_changes: int
    urgency_surcharges: int
    historical_entries: int
    pending_addon_facts: int
    multiple_rate_types: int


class PriceApplicationIssue(BaseModel):
    code: Literal["NOT_CONFIRMED", "CONFIRMATION_MISSING", "CONFIRMATION_MISMATCH", "MAILBOX_NOT_VERIFIED", "SUPERSEDED_CONFIRMED",
                  "NO_ITEMS", "MISSING_DOOR_PRICES", "MISSING_ADDON_PRICES", "UNAVAILABLE_WORK", "CATALOG_CHANGED",
                  "INSTALLER_SURCHARGES", "LEGACY_DIFFERENCES", "DOOR_SNAPSHOTS", "SCHEDULED_RATES",
                  "UNACCRUED_WORK", "URGENCY_CHARGES"]
    count: int


class PriceApplicationCheck(BaseModel):
    status: Literal["BLOCKED", "REVIEW_REQUIRED", "VERIFIED"]
    affects_earnings: Literal[False] = False
    confirmed_at: datetime | None
    blockers: list[PriceApplicationIssue]
    review: list[PriceApplicationIssue]


class ReconciliationPage(BaseModel):
    price_list_id: UUID | None
    version: int | None
    currency: Literal["ILS"]
    generated_at: datetime
    summary: ReconciliationSummary
    application_check: PriceApplicationCheck | None
    items: list[ReconciliationLine]
    total: int
