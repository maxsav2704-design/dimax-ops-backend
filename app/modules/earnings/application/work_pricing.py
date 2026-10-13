from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.modules.rates.application.timeline_dto import work_price_amount
from app.shared.domain.errors import Conflict


@dataclass(frozen=True)
class ApprovedWorkPrice:
    """Server-only terms for one reviewed work, never an installer input DTO."""

    company_id: UUID
    project_id: UUID
    installer_id: UUID
    kind: str
    target_id: UUID
    door_id: UUID | None
    performed_at: datetime
    quantity: Decimal
    rate: Decimal

    def amount(self, quantity):
        if Decimal(str(quantity)) != self.quantity:
            raise Conflict("Quantity differs from the factory-confirmed work")
        return work_price_amount(self.kind, self.rate, self.quantity)

    def validate_target(self, *, company_id, kind, target_id, performed_at):
        if (company_id, kind, target_id, performed_at) != (
                self.company_id, self.kind, self.target_id, self.performed_at):
            raise Conflict("Factory confirmation belongs to another work")

    def validate_work(self, work):
        if (work.company_id, work.project_id, work.installer_id, work.work_kind,
                work.door_id, work.completed_at, work.entry_type, work.rate_snapshot,
                work.amount_snapshot) != (
                self.company_id, self.project_id, self.installer_id, self.kind,
                self.door_id, self.performed_at, "ORIGINAL", self.rate, self.amount(work.quantity)):
            raise Conflict("Earning differs from the factory-confirmed work")
