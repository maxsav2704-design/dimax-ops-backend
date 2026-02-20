from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


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
    default_client_price: Decimal = Decimal("0")
    default_installer_price: Decimal = Decimal("0")


class AddonTypeListResponse(BaseModel):
    items: list[AddonTypeDTO]


class SetProjectPlanBody(BaseModel):
    addon_type_id: UUID
    qty_planned: Decimal
    client_price: Decimal
    installer_price: Decimal


class ProjectPlanItemDTO(BaseModel):
    addon_type_id: UUID
    qty_planned: Decimal
    client_price: Decimal
    installer_price: Decimal


class ProjectPlanResponse(BaseModel):
    project_id: UUID
    items: list[ProjectPlanItemDTO]
