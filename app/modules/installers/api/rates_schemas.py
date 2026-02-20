from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class InstallerRateCreateDTO(BaseModel):
    installer_id: uuid.UUID
    door_type_id: uuid.UUID
    price: Decimal = Field(ge=0)


class InstallerRateUpdateDTO(BaseModel):
    price: Optional[Decimal] = Field(default=None, ge=0)


class InstallerRateDTO(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    installer_id: uuid.UUID
    door_type_id: uuid.UUID
    price: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
