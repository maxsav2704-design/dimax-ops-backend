from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class AddonTypeDTO(BaseModel):
    id: UUID
    name: str
    unit: str
    default_client_price: Decimal
    default_installer_price: Decimal
    is_active: bool


class CreateAddonTypeBody(BaseModel):
    name: str
    unit: str = "pcs"
    default_client_price: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=12, decimal_places=2
    )
    default_installer_price: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=12, decimal_places=2
    )


class AddonTypeListResponse(BaseModel):
    items: list[AddonTypeDTO]


class SetProjectPlanBody(BaseModel):
    addon_type_id: UUID
    qty_planned: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    client_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    installer_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    notes: str | None = None


class ProjectPlanItemDTO(BaseModel):
    id: UUID | None = None
    addon_type_id: UUID
    addon_name: str | None = None
    qty_planned: Decimal
    client_price: Decimal
    installer_price: Decimal
    notes: str | None = None


class ProjectPlanResponse(BaseModel):
    project_id: UUID
    items: list[ProjectPlanItemDTO]
