import hashlib
import secrets
from datetime import timedelta
from hmac import compare_digest
from uuid import UUID, uuid4

from app.modules.audit.application.service import AuditService
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.rates.application.approval_verification import VerificationRejected, request_code, verify_code
from app.modules.sync.application.price_resolution_service import PriceConflictResolutionService
from app.modules.sync.application.work_price_approval_dto import PublicWorkPriceApproval, WorkPriceApprovalPage, WorkPriceApprovalSummary
from app.modules.sync.application.work_price_proposal_dto import ReviewWorkPriceProposal
from app.modules.sync.application.work_price_proposal_service import WorkPriceProposalService, _digest
from app.modules.sync.infrastructure.models import WorkPriceProposalORM
from app.modules.sync.infrastructure.work_price_approval_model import WorkPriceApprovalORM
from app.shared.domain.errors import Conflict, NotFound
from app.shared.infrastructure.db.base import utcnow


class WorkPriceApprovalService:
    """An independent factory decision; never a work ACK or an earning."""

    @staticmethod
    def _proposal(uow, company_id, proposal_id, *, validate=True):
        row = uow.session.query(WorkPriceProposalORM).filter_by(company_id=company_id, id=proposal_id).one_or_none()
        if row is None:
            raise NotFound("Work price proposal unavailable")
        if not compare_digest(_digest(row.snapshot), row.snapshot_hash):
            raise Conflict("Proposal snapshot changed")
        if validate:
            scope = row.snapshot["scope"]
            current, latest = WorkPriceProposalService._inspect(uow, company_id=company_id,
                source=scope["source"], item_id=UUID(scope["item_id"]),
                body=ReviewWorkPriceProposal(execution_correction=scope["execution_correction"]))
            if latest is None or latest.id != row.id:
                raise Conflict("Proposal has been superseded")
            # _inspect now points to this proposal; compare the original pre-save context.
            current["previous_proposal_id"] = row.snapshot["previous_proposal_id"]
            if any(current[key] != row.snapshot[key] for key in current):
                raise Conflict("Work changed; prepare a new proposal")
        return row

    @staticmethod
    def _reference(uow, proposal):
        door_id = proposal.snapshot["work_state"].get("door_id")
        if door_id:
            door = uow.session.query(DoorORM).filter_by(company_id=proposal.company_id, id=UUID(door_id)).one()
            return " / ".join(str(value) for value in (door.door_code or door.unit_label, door.house_number,
                                                       door.floor_label, door.apartment_number, door_id) if value)
        return proposal.snapshot["scope"]["item_id"]

    @classmethod
    def issue(cls, uow, *, company_id, proposal_id, actor_user_id, body):
        from app.modules.sync.application.work_price_email import enqueue_invitation
        from app.modules.rates.application.approval_email import validate_email_delivery
        PriceConflictResolutionService.require_authority(uow, company_id, actor_user_id)
        fingerprint = _digest({"proposal_id": str(proposal_id), "actor": str(actor_user_id),
            **body.model_dump(mode="json", exclude={"request_id"})})
        previous = uow.session.query(WorkPriceApprovalORM).filter_by(company_id=company_id, request_id=body.request_id).one_or_none()
        if previous:
            if previous.request_fingerprint != fingerprint:
                raise Conflict("Request ID already used for another invitation")
            return WorkPriceApprovalSummary.model_validate(previous)
        proposal = cls._proposal(uow, company_id, proposal_id)
        if not compare_digest(proposal.snapshot_hash, body.proposal_hash):
            raise Conflict("Proposal changed; reload before sending")
        contact = uow.price_lists.factory_contact(company_id)
        if contact is None or contact.id != body.factory_contact_id:
            raise Conflict("Factory contact changed or is not owner-approved")
        approvals = uow.session.query(WorkPriceApprovalORM).filter_by(company_id=company_id, proposal_id=proposal_id)
        if approvals.filter(WorkPriceApprovalORM.confirmed_at.is_not(None)).first():
            raise Conflict("This proposal already has an immutable factory decision")
        base = validate_email_delivery()
        now = utcnow()
        for old in approvals.filter_by(confirmed_at=None, revoked_at=None):
            old.revoked_at, old.revoked_by, old.revocation_reason = now, actor_user_id, "Replaced by a new invitation"
        uow.session.flush()
        token = secrets.token_urlsafe(32)
        snapshot = {"proposal_hash": proposal.snapshot_hash, "company_name": uow.price_lists.company(company_id).name,
            "proposal": proposal.snapshot, "reference": cls._reference(uow, proposal)}
        invitation = WorkPriceApprovalORM(id=uuid4(), company_id=company_id, proposal_id=proposal_id,
            request_id=body.request_id, request_fingerprint=fingerprint, created_by=actor_user_id, created_at=now,
            expires_at=now + timedelta(hours=body.expires_in_hours), factory_contact_id=contact.id,
            factory_name=contact.factory_name, recipient_name=contact.recipient_name, recipient_email=contact.recipient_email,
            token_hash=hashlib.sha256(token.encode()).hexdigest(), snapshot_hash=_digest(snapshot), snapshot=snapshot)
        # Enqueue before inserting the required outbox FK, in the same UOW transaction.
        message = enqueue_invitation(uow, invitation, token, base)
        invitation.email_outbox_id = message.id
        uow.session.add(invitation)
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id,
            entity_type="WORK_PRICE_APPROVAL", entity_id=invitation.id, action="INVITE",
            after={"proposal_id": str(proposal_id), "snapshot_hash": invitation.snapshot_hash,
                "factory_contact_id": str(contact.id), "email_outbox_id": str(message.id), "affects_earnings": False})
        return WorkPriceApprovalSummary.model_validate(invitation)

    @classmethod
    def history(cls, uow, *, company_id, proposal_id, actor_user_id, limit=20, offset=0):
        PriceConflictResolutionService.require_authority(uow, company_id, actor_user_id)
        cls._proposal(uow, company_id, proposal_id, validate=False)
        rows = uow.session.query(WorkPriceApprovalORM).filter_by(company_id=company_id, proposal_id=proposal_id)
        return WorkPriceApprovalPage(total=rows.count(), items=[WorkPriceApprovalSummary.model_validate(row)
            for row in rows.order_by(WorkPriceApprovalORM.created_at.desc(), WorkPriceApprovalORM.id).offset(offset).limit(limit)])

    @staticmethod
    def revoke(uow, *, company_id, proposal_id, approval_id, actor_user_id, reason):
        PriceConflictResolutionService.require_authority(uow, company_id, actor_user_id)
        row = uow.session.query(WorkPriceApprovalORM).filter_by(company_id=company_id, proposal_id=proposal_id, id=approval_id).one_or_none()
        if row is None:
            raise NotFound("Invitation unavailable")
        if row.confirmed_at:
            raise Conflict("A recorded factory decision cannot be revoked")
        if row.revoked_at is None:
            row.revoked_at, row.revoked_by, row.revocation_reason = utcnow(), actor_user_id, reason
            AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id,
                entity_type="WORK_PRICE_APPROVAL", entity_id=row.id, action="REVOKE", reason=reason[:500])
        return WorkPriceApprovalSummary.model_validate(row)

    @classmethod
    def _resolve(cls, uow, token):
        scope = uow.session.query(WorkPriceApprovalORM.company_id, WorkPriceApprovalORM.id).filter_by(
            token_hash=hashlib.sha256(token.encode()).hexdigest()).one_or_none()
        if scope is None or not uow.price_lists.lock_company(scope.company_id):
            raise NotFound("Invitation unavailable")
        row = uow.session.query(WorkPriceApprovalORM).filter_by(company_id=scope.company_id, id=scope.id).one()
        now = utcnow()
        if not uow.price_lists.company(scope.company_id).is_active or row.revoked_at or row.expires_at <= now:
            raise NotFound("Invitation unavailable")
        proposal = cls._proposal(uow, row.company_id, row.proposal_id, validate=row.confirmed_at is None)
        if (_digest(row.snapshot) != row.snapshot_hash or row.snapshot["proposal_hash"] != proposal.snapshot_hash
                or row.snapshot["proposal"] != proposal.snapshot):
            raise Conflict("Invitation no longer matches the proposal")
        if row.confirmed_at is None:
            contact = uow.price_lists.factory_contact(row.company_id)
            if contact is None or contact.id != row.factory_contact_id or any(getattr(contact, key) != getattr(row, key)
                    for key in ("factory_name", "recipient_name", "recipient_email")):
                raise NotFound("Invitation unavailable")
            if cls._reference(uow, proposal) != row.snapshot["reference"]:
                raise Conflict("Work identity changed; request a new invitation")
        return row, proposal, now

    @staticmethod
    def _public(row):
        snapshot, proposal = row.snapshot, row.snapshot["proposal"]
        scope = proposal["scope"]
        return PublicWorkPriceApproval(company_name=snapshot["company_name"], factory_name=row.factory_name,
            recipient_name=row.recipient_name, version=proposal["version"], currency="ILS", reason=proposal["reason"],
            agreement_reference=proposal["agreement_reference"], snapshot_hash=row.snapshot_hash, expires_at=row.expires_at,
            status="CONFIRMED" if row.confirmed_at else "PENDING", confirmed_at=row.confirmed_at,
            confirmed_name=row.confirmed_name, mailbox_verified_at=row.mailbox_verified_at,
            items=[{"kind": scope["missing_price"]["kind"], "name": scope["work_label"], "unit": scope["unit"], "installer_price": proposal["rate"]}],
            work={"proposal_id": row.proposal_id, "project_name": scope["project_name"], "installer_name": scope["installer_name"],
                "reference": snapshot["reference"], "performed_at": scope["missing_price"]["performed_at"],
                "quantity": scope["quantity"], "amount": proposal["amount"]})

    @classmethod
    def preview(cls, uow, *, token):
        row, _, _ = cls._resolve(uow, token)
        return cls._public(row)

    @classmethod
    def request_code(cls, uow, *, token):
        from app.modules.sync.application.work_price_email import enqueue_code
        row, _, now = cls._resolve(uow, token)
        return request_code(uow, row, token, now, enqueue=enqueue_code)

    @classmethod
    def confirm(cls, uow, *, body, ip=None, user_agent=None):
        row, proposal, now = cls._resolve(uow, body.token)
        if body.expected_version != proposal.version or not compare_digest(body.snapshot_hash, row.snapshot_hash):
            raise Conflict("Confirmation does not match the displayed work proposal")
        if not verify_code(row, body.verification_code, now):
            return VerificationRejected()
        if row.confirmed_at:
            if body.signer_name != row.confirmed_name:
                raise Conflict("A factory decision is immutable")
            return cls._public(row)
        row.confirmed_at, row.mailbox_verified_at, row.confirmed_name = now, now, body.signer_name
        AuditService.add(uow, company_id=row.company_id, actor_user_id=None, entity_type="WORK_PRICE_APPROVAL",
            entity_id=row.id, action="CONFIRM", ip=ip, user_agent=user_agent,
            after={"actor_kind": "FACTORY_REPRESENTATIVE", "factory_contact_id": str(row.factory_contact_id),
                "proposal_id": str(proposal.id), "proposal_hash": proposal.snapshot_hash, "snapshot_hash": row.snapshot_hash,
                "confirmed_name": row.confirmed_name, "mailbox_verified_at": now.isoformat(), "affects_earnings": False})
        return cls._public(row)
