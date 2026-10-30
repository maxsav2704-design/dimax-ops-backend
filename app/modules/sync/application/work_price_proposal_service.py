import hashlib
import json
from decimal import Decimal

from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.audit.application.service import AuditService
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.earnings.infrastructure.ledger_queries import active_completed_work_filter
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.rates.application.timeline_dto import work_price_amount
from app.modules.rates.application.timeline_service import FactoryPriceTimelineService
from app.modules.sync.application.price_resolution_service import PriceConflictResolutionService
from app.modules.sync.application.price_review_service import PriceConflictReviewService, _uuid
from app.modules.sync.application.service import InstallerSyncService
from app.modules.sync.application.work_price_proposal_dto import (
    CreateWorkPriceProposal, ReviewWorkPriceProposal, WorkPriceProposal,
    WorkPriceProposalReview, WorkPriceScope,
)
from app.modules.sync.infrastructure.models import WorkPriceProposalORM
from app.shared.domain.errors import Conflict


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class WorkPriceProposalService:
    """Prepare immutable terms for one work. Never confirms, sends or accrues them."""

    @staticmethod
    def _key(source):
        return "sync_event_id" if source == "sync_event" else "sync_queue_item_id"

    @staticmethod
    def _result(row):
        return WorkPriceProposal(id=row.id, version=row.version, scope=row.snapshot["scope"],
            rate=row.rate, amount=row.amount, reason=row.snapshot["reason"],
            agreement_reference=row.snapshot["agreement_reference"],
            execution_evidence=row.snapshot["execution_evidence"], snapshot_hash=row.snapshot_hash,
            created_by=row.created_by, created_at=row.created_at)

    @staticmethod
    def _inspect(uow, *, company_id, source, item_id, body):
        row, installer, operation = PriceConflictReviewService.pending(
            uow, company_id=company_id, source=source, item_id=item_id, for_update=True)
        if installer is None or not installer.is_active or installer.deleted_at is not None:
            raise Conflict("Original installer is no longer available")
        project = uow.projects.get(company_id=company_id, project_id=row.project_id, for_update=True)
        if project is None:
            raise Conflict("Original project is no longer available")
        payload = row.payload or {}
        InstallerSyncService._validate_work_payload(operation, payload)
        InstallerSyncService._ensure_project_access(uow, company_id=company_id,
            project_id=row.project_id, installer_id=installer.id)
        work_state = {}
        if operation == "DOOR_SET_STATUS" and payload.get("status") == "INSTALLED":
            door_id = row.entity_id if source == "sync_queue" else _uuid(payload.get("door_id"))
            door = uow.doors.get(company_id=company_id, door_id=door_id,
                for_update=True, active_project_only=True) if door_id else None
            if door is None or door.project_id != row.project_id or door.installer_id != installer.id:
                raise Conflict("Door assignment changed; a price proposal cannot override it")
            expected = row.base_version if source == "sync_queue" else payload.get("base_version", payload.get("previous_version"))
            if type(expected) is not int or expected != door.version:
                raise Conflict("Door version must match the original work")
            if door.is_locked or door.status.value == "INSTALLED":
                raise Conflict("Door is locked or already installed")
            target = uow.session.query(DoorTypeORM).filter_by(company_id=company_id,
                id=door.door_type_id).with_for_update().one_or_none()
            if target is None or not target.is_active or target.deleted_at is not None:
                raise Conflict("Door type is no longer available")
            if uow.session.query(CompletedWorkORM).filter(
                    active_completed_work_filter(company_id), CompletedWorkORM.door_id == door.id,
                    CompletedWorkORM.work_kind == "DOOR").first():
                raise Conflict("Door already has an earning")
            if door.apply_surcharge_to_installer and Decimal(str(door.surcharge_pct or 100)) != 100:
                raise Conflict("Installer surcharge must be resolved separately")
            unit = "pcs"
            work_state = {"door_id": str(door.id), "version": door.version, "status": door.status.value, "type_name": target.name,
                "assignment_started_at": door.assignment_started_at.isoformat() if door.assignment_started_at else None}
        elif operation == "ADDON_FACT_CREATE":
            addon = uow.session.query(AddonTypeORM).filter_by(company_id=company_id,
                id=_uuid(payload.get("addon_type_id"))).with_for_update().one_or_none()
            if addon is None or not addon.is_active or addon.deleted_at is not None:
                raise Conflict("Additional work type is no longer available")
            event_id = row.client_event_id if source == "sync_event" else str(row.id)
            if uow.addon_facts.get_by_client_event(company_id=company_id, client_event_id=event_id):
                raise Conflict("Additional work has already been recorded")
            unit = addon.unit.strip()
            if not unit:
                raise Conflict("Additional work unit is missing")
            assignments = uow.session.query(DoorORM.id, DoorORM.assignment_started_at).filter_by(
                company_id=company_id, project_id=row.project_id, installer_id=installer.id,
            ).order_by(DoorORM.id).with_for_update().all()
            work_state = {"assignments": [{"door_id": str(item.id),
                "started_at": item.assignment_started_at.isoformat() if item.assignment_started_at else None}
                for item in assignments]}
        else:
            raise Conflict("Only retained installation or additional work can receive a proposal")

        review = PriceConflictReviewService.get(uow, company_id=company_id, source=source, item_id=item_id,
            lock_assignments=True, execution_correction=body.execution_correction)
        if review.analysis_code != "MISSING_FACTORY_PRICE" or review.missing_price is None:
            raise Conflict("A proposal requires a verified applicable price list with a missing rate")
        if review.seen_version_status not in ("MISSING", "AVAILABLE"):
            raise Conflict("The original price version is not verifiable")
        if review.seen_version_status == "AVAILABLE":
            seen = uow.price_lists.get(company_id, _uuid(review.seen_price_list_id))
            FactoryPriceTimelineService._receipt(uow, seen, at=review.missing_price.performed_at)
            seen_item = next((item for item in uow.price_lists.items(company_id, seen.id)
                if item.kind == review.work_kind and (item.door_type_id or item.addon_type_id) == review.missing_price.target_id), None)
            if seen_item is not None and seen_item.unit != unit:
                raise Conflict("Original quantity unit changed; a separate evidence review is required")
        # The missing-rate diagnostic returns before quantity validation; validate it here.
        work_price_amount(review.work_kind, Decimal("1"), review.quantity)
        scope = WorkPriceScope(source=source, item_id=item_id, project_id=project.id, project_name=project.name,
            installer_id=installer.id, installer_name=installer.full_name, work_label=review.work_label,
            quantity=Decimal(review.quantity), unit=unit, missing_price=review.missing_price,
            execution_correction=body.execution_correction)
        latest = uow.session.query(WorkPriceProposalORM).filter_by(company_id=company_id,
            **{WorkPriceProposalService._key(source): item_id}).order_by(WorkPriceProposalORM.version.desc()).first()
        snapshot = {"schema_version": 1, "company_id": str(company_id),
            "scope": scope.model_dump(mode="json"), "original_command": PriceConflictReviewService.original(row, source),
            "work_state": work_state, "previous_proposal_id": str(latest.id) if latest else None}
        return snapshot, latest

    @staticmethod
    def review(uow, *, company_id, actor_user_id, source, item_id, body: ReviewWorkPriceProposal):
        PriceConflictResolutionService.require_authority(uow, company_id, actor_user_id)
        snapshot, latest = WorkPriceProposalService._inspect(uow, company_id=company_id,
            source=source, item_id=item_id, body=body)
        return WorkPriceProposalReview(review_token=_digest(snapshot), scope=snapshot["scope"],
            latest=WorkPriceProposalService._result(latest) if latest else None)

    @staticmethod
    def create(uow, *, company_id, actor_user_id, source, item_id, body: CreateWorkPriceProposal):
        PriceConflictResolutionService.require_authority(uow, company_id, actor_user_id)
        fingerprint = _digest({"source": source, "item_id": str(item_id), "actor_user_id": str(actor_user_id),
            **body.model_dump(mode="json", exclude={"request_id"})})
        previous = uow.session.query(WorkPriceProposalORM).filter_by(
            company_id=company_id, request_id=body.request_id).one_or_none()
        if previous:
            if previous.request_fingerprint != fingerprint:
                raise Conflict("Request ID was used for another proposal", field="request_id")
            return WorkPriceProposalService._result(previous)
        snapshot, latest = WorkPriceProposalService._inspect(uow, company_id=company_id,
            source=source, item_id=item_id, body=body)
        if _digest(snapshot) != body.review_token:
            raise Conflict("Work or proposal changed; review again", field="review_token")
        scope = WorkPriceScope(**snapshot["scope"])
        amount = work_price_amount(scope.missing_price.kind, body.rate, scope.quantity)
        version = latest.version + 1 if latest else 1
        snapshot = {**snapshot, "version": version, "created_by": str(actor_user_id), "currency": "ILS",
            "rate": str(body.rate), "amount": str(amount), "reason": body.reason,
            "agreement_reference": body.agreement_reference, "execution_evidence": body.execution_evidence,
            "execution_evidence_confirmed": body.confirm_execution_evidence}
        proposal = WorkPriceProposalORM(company_id=company_id,
            **{WorkPriceProposalService._key(source): item_id}, version=version, created_by=actor_user_id,
            request_id=body.request_id, request_fingerprint=fingerprint, snapshot_hash=_digest(snapshot),
            snapshot=snapshot, rate=body.rate, amount=amount)
        uow.session.add(proposal)
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id,
            entity_type="WORK_PRICE_PROPOSAL", entity_id=proposal.id, action="WORK_PRICE_PROPOSED",
            reason=body.reason, after={"version": version, "source": source, "item_id": str(item_id),
                "snapshot_hash": proposal.snapshot_hash, "rate": str(body.rate), "amount": str(amount),
                "previous_proposal_id": snapshot["previous_proposal_id"], "affects_earnings": False})
        return WorkPriceProposalService._result(proposal)
