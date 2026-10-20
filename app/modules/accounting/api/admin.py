from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.accounting.application.dto import (
    CommercialPriceDetail, CommercialPricePage, ContractDraft, ContractPage,
    CreateCommercialPriceDraft, CreateContractDraft,
)
from app.modules.accounting.application.service import CommercialDraftService
from app.shared.domain.errors import ForbiddenScope

router = APIRouter(prefix="/admin/accounting/contracts", tags=["Admin / Commercial drafts"])


def require_draft_owner(response: Response, user: CurrentUser = Depends(require_admin)):
    if user.admin_scope != "OWNER":
        raise ForbiddenScope("Commercial draft preparation currently requires OWNER")
    response.headers["Cache-Control"] = "no-store"
    return user


@router.get("", response_model=ContractPage)
def list_contracts(
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    user=Depends(require_draft_owner), uow=Depends(get_uow),
):
    with uow:
        return CommercialDraftService.contracts(uow, user, limit=limit, offset=offset)


@router.post("", response_model=ContractDraft)
def create_contract(body: CreateContractDraft, user=Depends(require_draft_owner), uow=Depends(get_uow)):
    with uow:
        return CommercialDraftService.create_contract(uow, user, body)


@router.get("/{contract_id}/prices", response_model=CommercialPricePage)
def list_prices(
    contract_id: UUID, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    user=Depends(require_draft_owner), uow=Depends(get_uow),
):
    with uow:
        return CommercialDraftService.prices(uow, user, contract_id, limit=limit, offset=offset)


@router.post("/{contract_id}/prices", response_model=CommercialPriceDetail)
def create_price(
    contract_id: UUID, body: CreateCommercialPriceDraft,
    user=Depends(require_draft_owner), uow=Depends(get_uow),
):
    with uow:
        return CommercialDraftService.create_price(uow, user, contract_id, body)


@router.get("/{contract_id}/prices/{price_id}", response_model=CommercialPriceDetail)
def get_price(
    contract_id: UUID, price_id: UUID,
    user=Depends(require_draft_owner), uow=Depends(get_uow),
):
    with uow:
        return CommercialDraftService.get_price(uow, user, contract_id, price_id)
