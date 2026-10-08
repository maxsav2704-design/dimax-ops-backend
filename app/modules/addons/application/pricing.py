from decimal import Decimal

from app.modules.earnings.application.factory_pricing import FactoryEarningsPricing
from app.modules.rates.application.timeline_service import FactoryPriceTimelineService
from app.shared.domain.errors import Conflict, ValidationError


class AddonPlanPricing:
    """Current read prices and the write boundary for historical plan prices."""

    def __init__(self, uow, company_id):
        snapshot = FactoryPriceTimelineService.installer_snapshot(uow, company_id=company_id)
        self.factory_active = snapshot is not None
        self.rates = {item.target_id: item.rate for item in snapshot.items if item.kind == "ADDON"} if snapshot else {}

    def price(self, addon_type_id, legacy_price):
        return self.rates.get(addon_type_id) if self.factory_active else legacy_price

    @staticmethod
    def reject_override():
        raise Conflict("Installer prices come from the confirmed factory price list; omit the plan price",
            field="installer_price", meta={"reason": "FACTORY_ADDON_PRICE_REQUIRED"})

    @staticmethod
    def plan_write_price(uow, *, company_id, project_id, addon_type_id, submitted):
        # Caller holds the company lock before reading mode and the project plan.
        if not FactoryEarningsPricing.is_active(uow, company_id):
            if submitted is None:
                raise ValidationError("installer_price is required before factory pricing is enabled", field="installer_price")
            return submitted
        if submitted is not None:
            AddonPlanPricing.reject_override()
        existing = uow.addon_plans.get_by_project_type(
            company_id=company_id, project_id=project_id, addon_type_id=addon_type_id)
        return existing.installer_price if existing else Decimal("0")
