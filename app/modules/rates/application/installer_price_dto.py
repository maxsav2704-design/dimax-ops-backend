from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InstallerPriceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["DOOR", "ADDON"]
    target_id: UUID
    unit: str
    rate: Decimal = Field(gt=0)


class InstallerPriceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price_list_id: UUID
    version: int = Field(ge=1)
    currency: Literal["ILS"]
    effective_from: datetime
    items: list[InstallerPriceItem]
