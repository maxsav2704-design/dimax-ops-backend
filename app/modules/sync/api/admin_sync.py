from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.v1.deps import get_uow, require_admin
from app.api.v1.deps import CurrentUser, ensure_admin_can_view_rates
from app.modules.sync.application.price_review_dto import ExecutionTimeCorrection, PriceConflictReview, PriceConflictSource
from app.modules.sync.application.price_review_service import PriceConflictReviewService
from app.modules.sync.application.price_review_dto import PriceConflictResolution, ResolvePriceConflict
from app.modules.sync.application.price_resolution_service import PriceConflictResolutionService
from app.modules.sync.application.work_price_proposal_dto import (
    CreateWorkPriceProposal, ReviewWorkPriceProposal, WorkPriceProposal, WorkPriceProposalReview,
)
from app.modules.sync.application.work_price_proposal_service import WorkPriceProposalService
from app.modules.sync.application.work_price_approval_dto import IssueWorkPriceApproval, WorkPriceApprovalPage, WorkPriceApprovalSummary
from app.modules.sync.application.work_price_approval_service import WorkPriceApprovalService
from app.modules.rates.application.price_list_dto import CancelPriceList
from app.modules.sync.api.admin_schemas import (
    SyncProblemsResponseDTO,
    SyncResetLegacyResponse,
    SyncStateDTO,
    SyncStatsDTO,
)
from app.modules.sync.application.admin_api_service import AdminSyncApiService
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/sync", tags=["Admin Sync"])


@router.get("/states", response_model=list[SyncStateDTO])
def list_sync_states(
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    admin: CurrentUser = Depends(require_admin),
) -> list[SyncStateDTO]:
    with uow:
        return AdminSyncApiService.list_states(
            uow,
            company_id=admin.company_id,
        )


@router.get("/stats", response_model=SyncStatsDTO)
def get_sync_stats(
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    admin: CurrentUser = Depends(require_admin),
) -> SyncStatsDTO:
    with uow:
        return AdminSyncApiService.get_stats(
            uow,
            company_id=admin.company_id,
        )


@router.get("/problems", response_model=SyncProblemsResponseDTO)
def list_sync_problems(
    limit: int = Query(default=25, ge=1, le=100),
    installer_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(all|failed|conflict|pending|auth_required|price_conflict)$",
    ),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    admin: CurrentUser = Depends(require_admin),
) -> SyncProblemsResponseDTO:
    with uow:
        return AdminSyncApiService.list_problems(
            uow,
            company_id=admin.company_id,
            installer_id=installer_id,
            limit=limit,
            status_filter=status_filter,
        )


@router.get("/price-conflicts/{source}/{item_id}", response_model=PriceConflictReview)
def review_price_conflict(
    source: PriceConflictSource, item_id: UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow), admin: CurrentUser = Depends(require_admin),
) -> PriceConflictReview:
    with uow:
        ensure_admin_can_view_rates(uow, admin)
        return PriceConflictReviewService.get(uow, company_id=admin.company_id, source=source, item_id=item_id)


@router.post("/price-conflicts/{source}/{item_id}/execution-review", response_model=PriceConflictReview)
def review_execution_correction(
    source: PriceConflictSource, item_id: UUID, body: ExecutionTimeCorrection,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow), admin: CurrentUser = Depends(require_admin),
) -> PriceConflictReview:
    with uow:
        ensure_admin_can_view_rates(uow, admin)
        PriceConflictResolutionService.require_authority(uow, admin.company_id, admin.id)
        return PriceConflictReviewService.get(uow, company_id=admin.company_id, source=source,
            item_id=item_id, execution_correction=body)


@router.post("/price-conflicts/{source}/{item_id}/resolve", response_model=PriceConflictResolution)
def resolve_price_conflict(
    source: PriceConflictSource, item_id: UUID, body: ResolvePriceConflict,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow), admin: CurrentUser = Depends(require_admin),
) -> PriceConflictResolution:
    with uow:
        ensure_admin_can_view_rates(uow, admin)
        return PriceConflictResolutionService.resolve(uow, company_id=admin.company_id,
            actor_user_id=admin.id, source=source, item_id=item_id, body=body)


@router.post("/work-price-proposals/{proposal_id}/invitations", response_model=WorkPriceApprovalSummary)
def invite_work_price_factory(proposal_id: UUID, body: IssueWorkPriceApproval, response: Response,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow), admin: CurrentUser = Depends(require_admin)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        return WorkPriceApprovalService.issue(uow, company_id=admin.company_id,
            proposal_id=proposal_id, actor_user_id=admin.id, body=body)


@router.get("/work-price-proposals/{proposal_id}/invitations", response_model=WorkPriceApprovalPage)
def work_price_invitation_history(proposal_id: UUID, response: Response, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow), admin: CurrentUser = Depends(require_admin)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        return WorkPriceApprovalService.history(uow, company_id=admin.company_id,
            proposal_id=proposal_id, actor_user_id=admin.id, limit=limit, offset=offset)


@router.post("/work-price-proposals/{proposal_id}/invitations/{approval_id}/revoke", response_model=WorkPriceApprovalSummary)
def revoke_work_price_invitation(proposal_id: UUID, approval_id: UUID, body: CancelPriceList, response: Response,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow), admin: CurrentUser = Depends(require_admin)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        return WorkPriceApprovalService.revoke(uow, company_id=admin.company_id, proposal_id=proposal_id,
            approval_id=approval_id, actor_user_id=admin.id, reason=body.reason)


@router.post("/price-conflicts/{source}/{item_id}/work-price-proposals/review", response_model=WorkPriceProposalReview)
def review_work_price_proposal(
    source: PriceConflictSource, item_id: UUID, body: ReviewWorkPriceProposal,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow), admin: CurrentUser = Depends(require_admin),
) -> WorkPriceProposalReview:
    with uow:
        ensure_admin_can_view_rates(uow, admin)
        return WorkPriceProposalService.review(uow, company_id=admin.company_id,
            actor_user_id=admin.id, source=source, item_id=item_id, body=body)


@router.post("/price-conflicts/{source}/{item_id}/work-price-proposals", response_model=WorkPriceProposal)
def create_work_price_proposal(
    source: PriceConflictSource, item_id: UUID, body: CreateWorkPriceProposal,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow), admin: CurrentUser = Depends(require_admin),
) -> WorkPriceProposal:
    with uow:
        ensure_admin_can_view_rates(uow, admin)
        return WorkPriceProposalService.create(uow, company_id=admin.company_id,
            actor_user_id=admin.id, source=source, item_id=item_id, body=body)


@router.post(
    "/states/{installer_id}/reset",
    response_model=SyncStateDTO,
    summary="Reset sync state for installer",
    description="Resets sync state for the given installer (user with role INSTALLER). installer_id = user id. Returns updated SyncStateDTO.",
)
def reset_sync_state_for_installer(
    installer_id: UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    admin: CurrentUser = Depends(require_admin),
) -> SyncStateDTO:
    with uow:
        return AdminSyncApiService.reset_state_for_user(
            uow,
            company_id=admin.company_id,
            user_id=installer_id,
            actor_user_id=admin.id,
        )


@router.post("/reset/{installer_id}", response_model=SyncResetLegacyResponse)
def reset_sync_state_legacy(
    installer_id: UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    admin: CurrentUser = Depends(require_admin),
) -> SyncResetLegacyResponse:
    with uow:
        return AdminSyncApiService.reset_state_legacy(
            uow,
            company_id=admin.company_id,
            installer_id=installer_id,
            actor_user_id=admin.id,
        )
