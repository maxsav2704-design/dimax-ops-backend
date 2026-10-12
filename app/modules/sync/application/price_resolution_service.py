import hashlib
import json
from uuid import UUID

from app.modules.audit.application.service import AuditService
from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.earnings.application.factory_pricing import FactoryEarningsPricing
from app.modules.earnings.infrastructure.ledger_queries import active_completed_work_filter
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.sync.application.price_review_dto import PriceConflictResolution, ResolvePriceConflict
from app.modules.sync.application.price_review_service import PriceConflictReviewService, _uuid
from app.modules.sync.application.service import InstallerSyncService, _SyncConflictError
from app.modules.sync.infrastructure.models import SyncPriceResolutionORM
from app.shared.domain.errors import Conflict, Forbidden


class PriceConflictResolutionService:
    """Explicitly accept execution-time terms, never a caller-supplied rate or amount."""

    @staticmethod
    def _result(row):
        return PriceConflictResolution(id=row.id, completed_work_id=row.completed_work_id,
            price_list_id=row.quote_snapshot["price_list_id"], amount=row.amount,
            resolved_at=row.resolved_at, reason=row.reason)

    @staticmethod
    def resolve(uow, *, company_id: UUID, actor_user_id: UUID, source, item_id: UUID,
                body: ResolvePriceConflict) -> PriceConflictResolution:
        FactoryEarningsPricing.lock_company(uow, company_id)
        # The same live OWNER/OPERATIONS + rates authority as a factory-price transition.
        if not uow.price_lists.can_activate_prices(company_id, actor_user_id):
            raise Forbidden("Only an authorized company administrator may resolve price conflicts")
        fingerprint = hashlib.sha256(json.dumps({"source": source, "item_id": str(item_id),
            "actor_user_id": str(actor_user_id),
            **body.model_dump(mode="json", exclude={"request_id", "confirm_execution_evidence"}),
            **({"confirm_execution_evidence": True} if body.confirm_execution_evidence else {})},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        decisions = uow.session.query(SyncPriceResolutionORM).filter_by(company_id=company_id)
        previous = decisions.filter_by(request_id=body.request_id).one_or_none()
        if previous is not None:
            if previous.request_fingerprint != fingerprint:
                raise Conflict("Request ID was used for another decision", field="request_id")
            return PriceConflictResolutionService._result(previous)
        key = "sync_event_id" if source == "sync_event" else "sync_queue_item_id"
        if decisions.filter_by(**{key: item_id}).first() is not None:
            raise Conflict("This work already has a price decision; reload the queue")
        row, installer, operation = PriceConflictReviewService.pending(
            uow, company_id=company_id, source=source, item_id=item_id, for_update=True)
        if installer is None or not installer.is_active or installer.deleted_at is not None:
            raise Conflict("Original installer is no longer available")
        project = uow.projects.get(company_id=company_id, project_id=row.project_id, for_update=True)
        if project is None:
            raise Conflict("Original project is no longer available")
        original = PriceConflictReviewService.original(row, source)
        payload = dict(row.payload or {})
        InstallerSyncService._validate_work_payload(operation, payload)
        work_query = uow.session.query(CompletedWorkORM).filter(active_completed_work_filter(company_id))
        if operation == "DOOR_SET_STATUS":
            door_id = row.entity_id if source == "sync_queue" else _uuid(payload.get("door_id"))
            if door_id is None:
                raise Conflict("Original door identifier is invalid")
            door = uow.doors.get(company_id=company_id, door_id=door_id, for_update=True, active_project_only=True)
            if door is None or door.project_id != row.project_id or door.installer_id != installer.id:
                raise Conflict("Door assignment changed; price resolution cannot override it")
            if work_query.filter_by(door_id=door_id).first() is not None:
                raise Conflict("Door already has an earning; use the separate correction process")
            payload["door_id"] = str(door_id)
        else:
            door_id = None
            uow.session.query(AddonTypeORM).filter_by(company_id=company_id,
                id=_uuid(payload.get("addon_type_id"))).with_for_update().first()
        event_id = row.client_event_id if source == "sync_event" else str(row.id)
        if operation == "ADDON_FACT_CREATE" and uow.addon_facts.get_by_client_event(
                company_id=company_id, client_event_id=event_id) is not None:
            raise Conflict("Additional work already exists; price resolution cannot rewrite it")

        review = PriceConflictReviewService.get(uow, company_id=company_id, source=source, item_id=item_id,
                                               lock_assignments=True)
        if not review.resolution_available or not review.review_token:
            raise Conflict("This conflict needs additional evidence; no automatic price resolution is available")
        if review.review_token != body.review_token:
            raise Conflict("Work or price evidence changed; review it again", field="review_token")
        if review.requires_execution_evidence and not body.confirm_execution_evidence:
            raise Conflict("Confirm independent execution and assignment evidence before accruing this work",
                           field="confirm_execution_evidence")
        quote = review.applicable_quote
        # Only a derived in-memory command uses the approved decision. The retained command never changes.
        if quote.selection == "FIRST_CONFIRMED_LEGACY":
            payload.pop("price_list_id", None)
        else:
            payload["price_list_id"] = str(quote.price_list_id)
        try:
            if operation == "DOOR_SET_STATUS":
                args = dict(company_id=company_id, installer_id=installer.id, actor_user_id=actor_user_id,
                    project_id=row.project_id, payload=payload, happened_at=row.client_happened_at,
                    reviewed_execution=True)
                if source == "sync_queue":
                    InstallerSyncService._apply_batch_door_set_status(uow, base_version=row.base_version, **args)
                else:
                    InstallerSyncService._apply_door_set_status(uow, **args)
                work = work_query.filter_by(door_id=door_id).one()
            else:
                InstallerSyncService._apply_addon_fact_create(uow, company_id=company_id,
                    installer_id=installer.id, project_id=row.project_id, payload=payload,
                    client_event_id=event_id, happened_at=row.client_happened_at, reviewed_execution=True)
                fact = uow.addon_facts.get_by_client_event(company_id=company_id, client_event_id=event_id)
                work = work_query.filter_by(addon_fact_id=fact.id).one()
        except _SyncConflictError as exc:
            raise Conflict(exc.message, meta={"conflict_code": exc.conflict_code}) from exc
        proof = FactoryEarningsPricing.evidence(uow, company_id, work.id)
        if (proof is None or proof.price_list_id != quote.price_list_id or proof.approval_id != quote.approval_id
                or proof.snapshot_hash != quote.snapshot_hash or proof.activation_id != quote.activation_id
                or proof.price_list_item_id != quote.price_list_item_id or work.rate_snapshot != quote.rate
                or work.amount_snapshot != review.preview_amount or work.completed_at != row.client_happened_at
                or work.installer_id != installer.id or work.project_id != row.project_id):
            raise Conflict("Applied work does not match the reviewed factory price; decision rolled back")
        decision = SyncPriceResolutionORM(company_id=company_id, **{key: row.id},
            completed_work_id=work.id, actor_user_id=actor_user_id, request_id=body.request_id,
            request_fingerprint=fingerprint, review_token=body.review_token, reason=body.reason,
            original_command=original, quote_snapshot={**quote.model_dump(mode="json"),
                "execution_evidence_confirmed": body.confirm_execution_evidence,
                "analysis_code": review.analysis_code}, amount=work.amount_snapshot)
        uow.session.add(decision)
        if source == "sync_event":
            uow.sync_events.mark_applied(row)
        else:
            uow.sync_queue.mark_applied(row)
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id,
            entity_type="SYNC_PRICE_RESOLUTION", entity_id=decision.id, action="SYNC_FACTORY_PRICE_RESOLVED",
            reason=body.reason, before=original,
            after={"completed_work_id": str(work.id), "price_list_id": str(quote.price_list_id),
                   "amount": str(work.amount_snapshot), "approval_id": str(quote.approval_id),
                   "execution_evidence_confirmed": body.confirm_execution_evidence,
                   "analysis_code": review.analysis_code})
        return PriceConflictResolutionService._result(decision)
