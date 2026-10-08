from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, ensure_admin_can_view_rates, get_uow, require_admin
from app.modules.rates.application.price_list_dto import (
    CancelPriceList, CreatePriceList, PriceListDetail, PriceListPage,
)
from app.modules.rates.application.price_lists_service import FactoryPriceListsService
from app.modules.rates.application.reconciliation_dto import ReconciliationPage
from app.modules.rates.application.reconciliation_service import FactoryPriceReconciliationService
from app.modules.rates.application.timeline_dto import CompanyPricingState
from app.modules.rates.application.timeline_service import FactoryPriceTimelineService

router = APIRouter(prefix="/admin/price-lists", tags=["Admin / Factory price lists"])


@router.get("", response_model=PriceListPage)
def list_price_lists(
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_admin), uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return FactoryPriceListsService.list(uow, company_id=user.company_id, limit=limit, offset=offset)


@router.get("/reconciliation", response_model=ReconciliationPage)
def reconcile_company_prices(
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    issues_only: bool = False, kind: Literal["DOOR", "ADDON"] | None = None,
    user: CurrentUser = Depends(require_admin), uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return FactoryPriceReconciliationService.get(uow, company_id=user.company_id, price_list_id=None,
            limit=limit, offset=offset, issues_only=issues_only, kind=kind)


@router.get("/state", response_model=CompanyPricingState)
def get_company_pricing_state(user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return FactoryPriceTimelineService.company_state(uow, company_id=user.company_id)


@router.get("/{price_list_id}", response_model=PriceListDetail)
def get_price_list(price_list_id: UUID, user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return FactoryPriceListsService.get(uow, company_id=user.company_id, price_list_id=price_list_id)


@router.get("/{price_list_id}/reconciliation", response_model=ReconciliationPage)
def reconcile_price_list(
    price_list_id: UUID, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    issues_only: bool = False, kind: Literal["DOOR", "ADDON"] | None = None,
    user: CurrentUser = Depends(require_admin), uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return FactoryPriceReconciliationService.get(uow, company_id=user.company_id, price_list_id=price_list_id,
            limit=limit, offset=offset, issues_only=issues_only, kind=kind)


@router.post("", response_model=PriceListDetail)
def create_price_list(body: CreatePriceList, user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return FactoryPriceListsService.create(uow, company_id=user.company_id, actor_user_id=user.id, body=body)


@router.post("/{price_list_id}/cancel", response_model=PriceListDetail)
def cancel_price_list(
    price_list_id: UUID, body: CancelPriceList,
    user: CurrentUser = Depends(require_admin), uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return FactoryPriceListsService.cancel(uow, company_id=user.company_id, actor_user_id=user.id,
                                               price_list_id=price_list_id, reason=body.reason)
