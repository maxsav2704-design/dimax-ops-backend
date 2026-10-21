from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.v1.deps import get_uow
from app.api.v1.rate_limit import rate_limit_factory_prices
from app.modules.accounting.api.admin import require_draft_owner
from app.modules.accounting.application.approval_dto import (
    ApprovalCandidate, CommercialApprovalDetail, CommercialApprovalPage, CommercialApprovalSummary,
    ConfirmCommercialApproval, IssueCommercialApproval, PublicCommercialApproval, RevokeCommercialApproval,
)
from app.modules.accounting.application.approval_service import CommercialApprovalService as Service
from app.modules.rates.application.approval_dto import PreviewApproval, RequestedApprovalCode
from app.modules.rates.application.approval_verification import VerificationRejected
from app.shared.domain.errors import Forbidden

admin_router = APIRouter(prefix="/admin/accounting/contracts", tags=["Admin / Commercial approval"])


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


public_router = APIRouter(prefix="/public/commercial-approvals", tags=["Public / Commercial approval"],
    dependencies=[Depends(rate_limit_factory_prices), Depends(no_store)])


@admin_router.get("/{contract_id}/approval-preview", response_model=ApprovalCandidate)
def candidate(contract_id: UUID, terms_id: UUID, price_id: UUID,
              user=Depends(require_draft_owner), uow=Depends(get_uow)):
    with uow:
        return Service.candidate(uow, user, contract_id, terms_id, price_id)


@admin_router.post("/{contract_id}/approvals", response_model=CommercialApprovalSummary)
def issue(contract_id: UUID, body: IssueCommercialApproval, user=Depends(require_draft_owner), uow=Depends(get_uow)):
    with uow:
        return Service.issue(uow, user, contract_id, body)


@admin_router.get("/{contract_id}/approvals", response_model=CommercialApprovalPage)
def history(contract_id: UUID, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
            user=Depends(require_draft_owner), uow=Depends(get_uow)):
    with uow:
        return Service.history(uow, user, contract_id, limit, offset)


@admin_router.get("/{contract_id}/approvals/{approval_id}", response_model=CommercialApprovalDetail)
def detail(contract_id: UUID, approval_id: UUID, user=Depends(require_draft_owner), uow=Depends(get_uow)):
    with uow:
        return Service.detail(uow, user, contract_id, approval_id)


@admin_router.post("/{contract_id}/approvals/{approval_id}/revoke", response_model=CommercialApprovalSummary)
def revoke(contract_id: UUID, approval_id: UUID, body: RevokeCommercialApproval,
           user=Depends(require_draft_owner), uow=Depends(get_uow)):
    with uow:
        return Service.revoke(uow, user, contract_id, approval_id, body.reason)


@public_router.post("/preview", response_model=PublicCommercialApproval)
def preview(body: PreviewApproval, uow=Depends(get_uow)):
    with uow:
        return Service.preview(uow, body.token)


@public_router.post("/request-code", response_model=RequestedApprovalCode)
def request_code(body: PreviewApproval, uow=Depends(get_uow)):
    with uow:
        return Service.request_code(uow, body.token)


@public_router.post("/confirm", response_model=PublicCommercialApproval)
def confirm(body: ConfirmCommercialApproval, request: Request, uow=Depends(get_uow)):
    with uow:
        result = Service.confirm(uow, body, ip=request.client.host if request.client else None,
                                 user_agent=request.headers.get("user-agent"))
    # Failed mailbox attempts must commit before returning the HTTP error.
    if isinstance(result, VerificationRejected):
        raise Forbidden("A valid mailbox code is required; request a new invitation if the attempt limit was reached")
    return result
