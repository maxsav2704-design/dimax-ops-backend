from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.rates.application.timeline_dto import FactoryPriceQuote

PriceConflictSource = Literal["sync_event", "sync_queue"]


class PriceConflictReview(BaseModel):
    source: PriceConflictSource
    id: UUID
    project_id: UUID | None
    project_name: str | None = None
    installer_id: UUID | None
    installer_name: str | None = None
    work_kind: Literal["DOOR", "ADDON"] | None = None
    work_label: str | None = None
    performed_at: datetime | None
    received_at: datetime
    quantity: str | None = None
    seen_price_list_id: str | None = None
    seen_version: int | None = None
    seen_version_status: Literal["MISSING", "INVALID", "UNAVAILABLE", "AVAILABLE"] = "MISSING"
    analysis_code: Literal[
        "VERSION_MISMATCH", "VERSION_MATCH", "NO_VERSION", "INVALID_VERSION",
        "MISSING_EXECUTION_TIME", "INVALID_EXECUTION_TIME", "NO_ACTIVE_FACTORY_PRICES",
        "MISSING_FACTORY_PRICE", "INVALID_FACTORY_EVIDENCE", "WORK_UNAVAILABLE",
        "INVALID_QUANTITY", "UNSUPPORTED_WORK", "CATALOG_UNIT_CHANGED",
    ]
    applicable_quote: FactoryPriceQuote | None = None
    preview_amount: Decimal | None = None
    work_context: Literal["CURRENT_CATALOG"] = "CURRENT_CATALOG"
    resolution_available: Literal[False] = False
