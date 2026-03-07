from __future__ import annotations

import uuid


class CompanyMetricsService:
    @staticmethod
    def limits_kpi(uow, *, company_id: uuid.UUID) -> dict:
        return uow.company_plans.limits_kpi(company_id)

