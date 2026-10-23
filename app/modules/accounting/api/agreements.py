from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import get_uow
from app.modules.accounting.api.admin import require_draft_owner
from app.modules.accounting.application.agreement_dto import (
    ActivateCommercialAgreement, CommercialAgreementPage, CommercialAgreementSummary, PeriodDetail, PeriodPage,
)
from app.modules.accounting.application.agreement_service import CommercialAgreementService
from app.modules.accounting.application.estimate_service import CommercialEstimateService

router = APIRouter(prefix="/admin/accounting/contracts", tags=["Admin / Commercial agreements"])


@router.get("/{contract_id}/agreements", response_model=CommercialAgreementPage)
def list_agreements(contract_id: UUID, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                    user=Depends(require_draft_owner), uow=Depends(get_uow)):
    with uow:
        return CommercialAgreementService.page(uow, user, contract_id, limit, offset)


@router.post("/{contract_id}/agreements", response_model=CommercialAgreementSummary)
def activate(contract_id: UUID, body: ActivateCommercialAgreement, user=Depends(require_draft_owner), uow=Depends(get_uow)):
    with uow:
        return CommercialAgreementService.activate(uow, user, contract_id, body)


@router.get("/{contract_id}/periods", response_model=PeriodPage)
def list_periods(contract_id: UUID, user=Depends(require_draft_owner), uow=Depends(get_uow)):
    with uow:
        return CommercialEstimateService.periods(uow, user, contract_id)


@router.get("/{contract_id}/periods/{start}", response_model=PeriodDetail)
def period_detail(contract_id: UUID, start: str, user=Depends(require_draft_owner), uow=Depends(get_uow)):
    with uow:
        return CommercialEstimateService.period(uow, user, contract_id, start)
