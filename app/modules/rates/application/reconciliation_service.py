from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.modules.rates.application.reconciliation_dto import ReconciliationLine, ReconciliationPage, ReconciliationSummary
from app.modules.rates.application.application_check_service import FactoryPriceApplicationCheckService
from app.shared.domain.errors import NotFound


class FactoryPriceReconciliationService:
    @staticmethod
    def get(uow, *, company_id: UUID, price_list_id: UUID | None, limit: int, offset: int,
            issues_only: bool, kind: str | None) -> ReconciliationPage:
        price_list = uow.price_lists.get(company_id, price_list_id) if price_list_id is not None else None
        if price_list_id is not None and price_list is None:
            raise NotFound("Price list not found")
        at = datetime.now(timezone.utc)
        rows = uow.price_lists.reconciliation_page(company_id=company_id, price_list_id=price_list_id,
            at=at, limit=limit, offset=offset, issues_only=issues_only, kind=kind)
        summary = ReconciliationSummary.model_validate(rows[0])
        return ReconciliationPage(
            price_list_id=price_list.id if price_list else None, version=price_list.version if price_list else None,
            currency=price_list.currency if price_list else "ILS",
            generated_at=at, summary=summary, total=rows[0]["total"],
            application_check=FactoryPriceApplicationCheckService.get(uow, price_list=price_list, summary=summary, at=at)
            if price_list else None,
            items=[ReconciliationLine.model_validate(row) for row in rows if row["source_id"] is not None],
        )
