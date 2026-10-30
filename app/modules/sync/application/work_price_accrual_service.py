from datetime import datetime
from decimal import Decimal
from hmac import compare_digest
from uuid import UUID

from app.modules.audit.application.service import AuditService
from app.modules.earnings.application.work_pricing import ApprovedWorkPrice
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.earnings.infrastructure.ledger_queries import active_completed_work_filter
from app.modules.earnings.infrastructure.work_price_models import WorkPriceAccrualORM
from app.modules.sync.application.price_resolution_service import PriceConflictResolutionService
from app.modules.sync.application.price_review_service import PriceConflictReviewService
from app.modules.sync.application.service import InstallerSyncService, _SyncConflictError
from app.modules.sync.application.work_price_accrual_dto import WorkPriceAccrual, WorkPriceAccrualReview
from app.modules.sync.application.work_price_approval_service import WorkPriceApprovalService
from app.modules.sync.application.work_price_proposal_service import _digest
from app.modules.sync.infrastructure.work_price_approval_model import WorkPriceApprovalORM
from app.shared.domain.errors import Conflict, NotFound
from app.shared.infrastructure.db.base import utcnow


class WorkPriceAccrualService:
    @staticmethod
    def _confirmed(uow, company_id, approval_id, *, validate_work):
        approval = uow.session.query(WorkPriceApprovalORM).filter_by(company_id=company_id, id=approval_id).one_or_none()
        if approval is None:
            raise NotFound("Work price confirmation unavailable")
        if (approval.confirmed_at is None or approval.mailbox_verified_at != approval.confirmed_at
                or approval.revoked_at is not None or not approval.confirmed_name
                or not approval.created_at <= approval.confirmed_at < approval.expires_at
                or approval.confirmed_at > utcnow()):
            raise Conflict("A mailbox-verified factory decision is required before accrual")
        proposal = WorkPriceApprovalService._proposal(uow, company_id, approval.proposal_id, validate=validate_work)
        if (not compare_digest(_digest(approval.snapshot), approval.snapshot_hash)
                or approval.snapshot["proposal_hash"] != proposal.snapshot_hash
                or approval.snapshot["proposal"] != proposal.snapshot):
            raise Conflict("Factory decision no longer matches the work proposal")
        if validate_work and WorkPriceApprovalService._reference(uow, proposal) != approval.snapshot["reference"]:
            raise Conflict("Work identity changed; a new factory confirmation is required")
        # A valid recorded decision survives link expiry/contact replacement, like a confirmed list.
        return approval, proposal

    @classmethod
    def review(cls, uow, *, company_id, actor_user_id, approval_id):
        PriceConflictResolutionService.require_authority(uow, company_id, actor_user_id)
        previous = uow.session.query(WorkPriceAccrualORM).filter_by(company_id=company_id, approval_id=approval_id).one_or_none()
        approval, proposal = cls._confirmed(uow, company_id, approval_id, validate_work=previous is None)
        return WorkPriceAccrualReview(approval_id=approval.id, approval_hash=approval.snapshot_hash,
            scope=proposal.snapshot["scope"], reference=approval.snapshot["reference"], rate=proposal.rate,
            amount=proposal.amount, confirmed_name=approval.confirmed_name, confirmed_at=approval.confirmed_at,
            accrual=WorkPriceAccrual.model_validate(previous) if previous else None)

    @classmethod
    def accrue(cls, uow, *, company_id, actor_user_id, approval_id, body):
        PriceConflictResolutionService.require_authority(uow, company_id, actor_user_id)
        fingerprint = _digest({"approval_id": str(approval_id), "actor_user_id": str(actor_user_id),
                               **body.model_dump(mode="json", exclude={"request_id"})})
        decisions = uow.session.query(WorkPriceAccrualORM).filter_by(company_id=company_id)
        previous = decisions.filter_by(request_id=body.request_id).one_or_none()
        if previous:
            if previous.request_fingerprint != fingerprint:
                raise Conflict("Request ID was used for another accrual")
            return WorkPriceAccrual.model_validate(previous)
        if decisions.filter_by(approval_id=approval_id).first():
            raise Conflict("This work has already been accrued; reload the decision")
        approval, proposal = cls._confirmed(uow, company_id, approval_id, validate_work=True)
        if not compare_digest(body.approval_hash, approval.snapshot_hash):
            raise Conflict("Factory decision changed; review it again")
        scope = proposal.snapshot["scope"]
        source, item_id = scope["source"], UUID(scope["item_id"])
        row, installer, operation = PriceConflictReviewService.pending(
            uow, company_id=company_id, source=source, item_id=item_id, for_update=True)
        context = scope["missing_price"]
        quote = ApprovedWorkPrice(company_id=company_id, project_id=row.project_id, installer_id=installer.id,
            kind=context["kind"], target_id=UUID(context["target_id"]),
            door_id=UUID(proposal.snapshot["work_state"]["door_id"]) if context["kind"] == "DOOR" else None,
            performed_at=datetime.fromisoformat(context["performed_at"]), quantity=Decimal(scope["quantity"]),
            rate=proposal.rate)
        if quote.amount(quote.quantity) != proposal.amount or proposal.rate != Decimal(proposal.snapshot["rate"]):
            raise Conflict("Stored work terms are inconsistent")
        payload = dict(row.payload or {})
        event_id = row.client_event_id if source == "sync_event" else str(row.id)
        args = dict(company_id=company_id, installer_id=installer.id, project_id=row.project_id,
                    payload=payload, happened_at=quote.performed_at, reviewed_execution=True, approved_work_price=quote)
        try:
            if operation == "DOOR_SET_STATUS":
                payload["door_id"] = str(quote.door_id)
                if source == "sync_queue":
                    InstallerSyncService._apply_batch_door_set_status(uow, actor_user_id=actor_user_id,
                        base_version=row.base_version, **args)
                else:
                    InstallerSyncService._apply_door_set_status(uow, actor_user_id=actor_user_id, **args)
                work = uow.session.query(CompletedWorkORM).filter(active_completed_work_filter(company_id)).filter_by(
                    door_id=quote.door_id, work_kind="DOOR").one()
            else:
                InstallerSyncService._apply_addon_fact_create(uow, client_event_id=event_id, **args)
                uow.session.flush()
                fact = uow.addon_facts.get_by_client_event(company_id=company_id, client_event_id=event_id)
                work = uow.session.query(CompletedWorkORM).filter_by(company_id=company_id, addon_fact_id=fact.id).one()
        except _SyncConflictError as exc:
            raise Conflict(exc.message, meta={"conflict_code": exc.conflict_code}) from exc
        quote.validate_work(work)
        source_key = "sync_event_id" if source == "sync_event" else "sync_queue_item_id"
        decision = WorkPriceAccrualORM(company_id=company_id, approval_id=approval_id, completed_work_id=work.id,
            **{source_key: item_id}, actor_user_id=actor_user_id, request_id=body.request_id,
            request_fingerprint=fingerprint, approval_hash=approval.snapshot_hash, reason=body.reason,
            snapshot={"approval": approval.snapshot, "confirmed_at": approval.confirmed_at.isoformat(),
                      "confirmed_name": approval.confirmed_name, "factory_contact_id": str(approval.factory_contact_id)},
            amount=work.amount_snapshot)
        uow.session.add(decision)
        if source == "sync_event":
            uow.sync_events.mark_applied(row)
        else:
            uow.sync_queue.mark_applied(row)
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id,
            entity_type="WORK_PRICE_ACCRUAL", entity_id=decision.id, action="ACCRUE", reason=body.reason,
            before=proposal.snapshot["original_command"], after={"completed_work_id": str(work.id),
                "approval_id": str(approval_id), "approval_hash": approval.snapshot_hash,
                "amount": str(work.amount_snapshot), "performed_at": quote.performed_at.isoformat()})
        return WorkPriceAccrual.model_validate(decision)
