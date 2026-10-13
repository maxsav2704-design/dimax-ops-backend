from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.v1.deps import CurrentUser, ensure_admin_can_view_rates, get_uow, require_admin
from app.api.v1.rate_limit import rate_limit_factory_prices
from app.modules.rates.application.approval_dto import (
    ApprovalPage, ApprovalSummary, ConfirmApproval, IssueApproval, IssuedApproval,
    PreviewApproval, PublicApproval, RequestedApprovalCode,
)
from app.modules.rates.application.approval_service import FactoryPriceApprovalService
from app.modules.rates.application.price_list_dto import CancelPriceList
from app.modules.rates.application.approval_verification import VerificationRejected
from app.modules.rates.application.contact_dto import FactoryContactView, RegisterFactoryContact, RevokeFactoryContact
from app.modules.rates.application.contact_service import FactoryContactService
from app.shared.domain.errors import Forbidden
from app.modules.sync.application.work_price_approval_dto import PublicWorkPriceApproval
from app.modules.sync.application.work_price_approval_service import WorkPriceApprovalService

admin_router = APIRouter(prefix="/admin/price-lists", tags=["Admin / Factory price lists"])
public_router = APIRouter(prefix="/public/price-approvals", tags=["Public / Factory prices"],
                         dependencies=[Depends(rate_limit_factory_prices)])


@public_router.post("/work/preview", response_model=PublicWorkPriceApproval)
def preview_work_price(body: PreviewApproval, response: Response, uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        return WorkPriceApprovalService.preview(uow, token=body.token)


@public_router.post("/work/request-code", response_model=RequestedApprovalCode)
def request_work_price_code(body: PreviewApproval, response: Response, uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        return WorkPriceApprovalService.request_code(uow, token=body.token)


@public_router.post("/work/confirm", response_model=PublicWorkPriceApproval)
def confirm_work_price(body: ConfirmApproval, response: Response, request: Request, uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        result = WorkPriceApprovalService.confirm(uow, body=body,
            ip=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
    if isinstance(result, VerificationRejected):
        raise Forbidden("A valid mailbox code is required; request a new invitation if the attempt limit was reached")
    return result


@admin_router.get("/factory/contact", response_model=FactoryContactView | None)
def factory_contact(response: Response, user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        ensure_admin_can_view_rates(uow, user)
        row = uow.price_lists.factory_contact(user.company_id)
        return FactoryContactView.model_validate(row) if row else None


@admin_router.post("/factory/contact", response_model=FactoryContactView)
def register_factory_contact(body: RegisterFactoryContact, response: Response,
                             user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        return FactoryContactService.register(uow, company_id=user.company_id, actor_user_id=user.id, body=body)


@admin_router.post("/factory/contact/revoke", response_model=None)
def revoke_factory_contact(body: RevokeFactoryContact, response: Response,
                           user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        FactoryContactService.revoke(uow, company_id=user.company_id, actor_user_id=user.id, body=body)
    return {"ok": True}


@admin_router.post("/{price_list_id}/approvals", response_model=IssuedApproval)
def issue_approval(price_list_id: UUID, body: IssueApproval, response: Response,
                   user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return FactoryPriceApprovalService.issue(uow, company_id=user.company_id,
            price_list_id=price_list_id, actor_user_id=user.id, body=body)


@admin_router.get("/{price_list_id}/approvals", response_model=ApprovalPage)
def approval_history(price_list_id: UUID, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                     user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return FactoryPriceApprovalService.history(uow, company_id=user.company_id,
            price_list_id=price_list_id, limit=limit, offset=offset)


@admin_router.post("/{price_list_id}/approvals/{approval_id}/revoke", response_model=ApprovalSummary)
def revoke_approval(price_list_id: UUID, approval_id: UUID, body: CancelPriceList,
                    user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return FactoryPriceApprovalService.revoke(uow, company_id=user.company_id,
            price_list_id=price_list_id, approval_id=approval_id, actor_user_id=user.id, reason=body.reason)


@public_router.post("/preview", response_model=PublicApproval)
def preview_approval(body: PreviewApproval, response: Response, uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        return FactoryPriceApprovalService.preview(uow, token=body.token)


@public_router.post("/confirm", response_model=PublicApproval)
def confirm_approval(body: ConfirmApproval, response: Response, request: Request, uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        result = FactoryPriceApprovalService.confirm(uow, body=body,
            ip=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
    if isinstance(result, VerificationRejected):
        raise Forbidden("A valid mailbox code is required; request a new invitation if the attempt limit was reached")
    return result


@public_router.post("/request-code", response_model=RequestedApprovalCode)
def request_approval_code(body: PreviewApproval, response: Response, uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        return FactoryPriceApprovalService.request_code(uow, token=body.token)
