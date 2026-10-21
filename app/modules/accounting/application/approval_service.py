import hashlib
import os
import secrets
from datetime import timedelta
from hmac import compare_digest
from uuid import uuid4

from app.modules.accounting.application.approval_dto import (
    ApprovalCandidate, CommercialAgreement, CommercialApprovalDetail, CommercialApprovalPage,
    CommercialApprovalSummary, PublicCommercialApproval,
)
from app.modules.accounting.application.service import CommercialDraftService, _fingerprint
from app.modules.accounting.infrastructure.approval_models import CommercialApprovalORM
from app.modules.accounting.infrastructure.approval_repository import CommercialApprovalRepository
from app.modules.audit.application.service import AuditService
from app.modules.rates.application.approval_email import validate_email_delivery
from app.modules.rates.application.approval_verification import VerificationRejected, request_code, verify_code
from app.modules.rates.application.contact_dto import FactoryContactView
from app.shared.domain.errors import Conflict, NotFound
from app.shared.infrastructure.db.base import utcnow


class CommercialApprovalService:
    """Evidence for one exact pair, never a billing activation or installer price."""

    @staticmethod
    def _owner(uow, user, contract_id):
        repo = CommercialApprovalRepository(uow.session)
        # Use the same company lock as factory contact rotation and public decisions.
        if not repo.lock_company(user.company_id):
            raise NotFound("Company unavailable")
        CommercialDraftService._repo(uow, user)
        contract = CommercialDraftService._contract(repo, user, contract_id)
        return repo, contract

    @staticmethod
    def _snapshot(uow, repo, contract, terms_id, price_id, *, latest=True, company_name=None):
        terms = repo.terms_version(contract.company_id, contract.id, terms_id)
        price = repo.price(contract.company_id, contract.id, price_id)
        if terms is None or price is None:
            raise NotFound("Contract version unavailable")
        if latest and (terms.version != repo.terms(contract.company_id, contract.id, 1, 0)[2]
                       or price.version != repo.prices(contract.company_id, contract.id, 1, 0)[2]):
            raise Conflict("Contract or price superseded; review both latest versions")
        snapshot = CommercialAgreement(company_id=contract.company_id,
            company_name=company_name or uow.price_lists.company(contract.company_id).name,
            contract_id=contract.id, contract_reference=contract.reference, factory_name=contract.factory_name,
            is_demo=contract.is_demo, terms=CommercialDraftService._terms_detail(terms, contract),
            price=CommercialDraftService._detail(repo, price, contract)).model_dump(mode="json")
        if not snapshot["price"]["items"]:
            raise Conflict("An empty commercial price cannot be confirmed")
        return snapshot

    @classmethod
    def candidate(cls, uow, user, contract_id, terms_id, price_id):
        repo, contract = cls._owner(uow, user, contract_id)
        snapshot = cls._snapshot(uow, repo, contract, terms_id, price_id)
        contact = uow.price_lists.factory_contact(user.company_id)
        return ApprovalCandidate(snapshot=snapshot, snapshot_hash=_fingerprint(snapshot),
                                 contact=FactoryContactView.model_validate(contact) if contact else None)

    @classmethod
    def issue(cls, uow, user, contract_id, body):
        from app.modules.accounting.application.approval_email import enqueue_invitation
        repo, contract = cls._owner(uow, user, contract_id)
        fingerprint = _fingerprint({"contract_id": str(contract_id), "actor": str(user.id),
            **body.model_dump(mode="json", exclude={"request_id"})})
        previous = repo.request(user.company_id, body.request_id)
        if previous:
            if previous.request_fingerprint != fingerprint:
                raise Conflict("Request ID already used for another invitation")
            return cls._summary(uow, repo, previous)
        if contract.is_demo and os.environ.get("APP_ENV", "").lower() != "test":
            raise Conflict("Demo contracts cannot be sent for real factory confirmation")
        snapshot = cls._snapshot(uow, repo, contract, body.terms_id, body.price_id)
        if not compare_digest(_fingerprint(snapshot), body.snapshot_hash):
            raise Conflict("Displayed contract versions changed; reload")
        contact = uow.price_lists.factory_contact(user.company_id)
        if contact is None or contact.id != body.factory_contact_id:
            raise Conflict("Factory contact changed or is not OWNER-approved")
        if repo.confirmed_pair(user.company_id, body.terms_id, body.price_id):
            raise Conflict("These exact versions already have a factory decision")
        base = validate_email_delivery()
        now = utcnow()
        for old in repo.pending(user.company_id, contract_id):
            old.revoked_at, old.revoked_by, old.revocation_reason = now, user.id, "Replaced by a new invitation"
        uow.session.flush()
        token = secrets.token_urlsafe(32)
        row = CommercialApprovalORM(id=uuid4(), company_id=user.company_id, contract_id=contract_id,
            terms_id=body.terms_id, price_id=body.price_id, request_id=body.request_id,
            request_fingerprint=fingerprint, factory_contact_id=contact.id, factory_name=contact.factory_name,
            recipient_name=contact.recipient_name, recipient_email=contact.recipient_email,
            snapshot=snapshot, snapshot_hash=_fingerprint(snapshot), token_hash=hashlib.sha256(token.encode()).hexdigest(),
            created_by=user.id, created_at=now, expires_at=now + timedelta(hours=body.expires_in_hours))
        message = enqueue_invitation(uow, row, token, base)
        row.email_outbox_id = message.id
        repo.add(row)
        AuditService.add(uow, company_id=user.company_id, actor_user_id=user.id,
            entity_type="COMMERCIAL_APPROVAL", entity_id=row.id, action="INVITE",
            after={"contract_id": str(contract_id), "terms_id": str(row.terms_id), "price_id": str(row.price_id),
                "snapshot_hash": row.snapshot_hash, "factory_contact_id": str(contact.id),
                "email_outbox_id": str(message.id), "is_demo": contract.is_demo})
        return cls._summary(uow, repo, row)

    @staticmethod
    def _contact_matches(uow, row):
        contact = uow.price_lists.factory_contact(row.company_id)
        return contact is not None and contact.id == row.factory_contact_id and all(
            getattr(contact, key) == getattr(row, key) for key in ("factory_name", "recipient_name", "recipient_email"))

    @classmethod
    def _summary(cls, uow, repo, row):
        status = "PENDING"
        if row.confirmed_at:
            status = "CONFIRMED"
        elif row.revoked_at:
            status = "REVOKED"
        elif row.expires_at <= utcnow():
            status = "EXPIRED"
        elif not cls._contact_matches(uow, row):
            status = "CONTACT_CHANGED"
        elif (row.snapshot["terms"]["version"] != repo.terms(row.company_id, row.contract_id, 1, 0)[2]
              or row.snapshot["price"]["version"] != repo.prices(row.company_id, row.contract_id, 1, 0)[2]):
            status = "SUPERSEDED"
        fields = {key: getattr(row, key) for key in CommercialApprovalSummary.model_fields
                  if hasattr(row, key)}
        return CommercialApprovalSummary(**fields, status=status, is_demo=row.snapshot["is_demo"],
            terms_version=row.snapshot["terms"]["version"], price_version=row.snapshot["price"]["version"],
            delivery_status=repo.delivery_status(row))

    @classmethod
    def history(cls, uow, user, contract_id, limit=20, offset=0):
        repo, _ = cls._owner(uow, user, contract_id)
        rows, total = repo.page(user.company_id, contract_id, limit, offset)
        return CommercialApprovalPage(items=[cls._summary(uow, repo, row) for row in rows], total=total)

    @classmethod
    def detail(cls, uow, user, contract_id, approval_id):
        repo, _ = cls._owner(uow, user, contract_id)
        row = repo.get(user.company_id, contract_id, approval_id)
        if row is None:
            raise NotFound("Invitation unavailable")
        return CommercialApprovalDetail(**cls._summary(uow, repo, row).model_dump(), snapshot=row.snapshot)

    @classmethod
    def revoke(cls, uow, user, contract_id, approval_id, reason):
        repo, _ = cls._owner(uow, user, contract_id)
        row = repo.get(user.company_id, contract_id, approval_id)
        if row is None:
            raise NotFound("Invitation unavailable")
        if row.confirmed_at:
            raise Conflict("A factory decision cannot be revoked; create amended versions")
        if row.revoked_at is None:
            row.revoked_at, row.revoked_by, row.revocation_reason = utcnow(), user.id, reason
            AuditService.add(uow, company_id=user.company_id, actor_user_id=user.id,
                entity_type="COMMERCIAL_APPROVAL", entity_id=row.id, action="REVOKE", reason=reason[:500])
        return cls._summary(uow, repo, row)

    @classmethod
    def _resolve(cls, uow, token):
        repo = CommercialApprovalRepository(uow.session)
        scope = repo.scope(hashlib.sha256(token.encode()).hexdigest())
        if scope is None or not repo.lock_company(scope.company_id):
            raise NotFound("Invitation unavailable")
        row = repo.get(scope.company_id, scope.contract_id, scope.id)
        now = utcnow()
        if row.revoked_at or row.expires_at <= now:
            raise NotFound("Invitation unavailable")
        if not row.confirmed_at and not cls._contact_matches(uow, row):
            raise NotFound("Invitation unavailable")
        contract = repo.contract(row.company_id, row.contract_id)
        if contract.is_demo and os.environ.get("APP_ENV", "").lower() != "test":
            raise NotFound("Invitation unavailable")
        current = cls._snapshot(uow, repo, contract, row.terms_id, row.price_id,
            latest=row.confirmed_at is None, company_name=row.snapshot["company_name"])
        if not compare_digest(_fingerprint(current), row.snapshot_hash) or not compare_digest(_fingerprint(row.snapshot), row.snapshot_hash):
            raise Conflict("Contract versions no longer match the invitation")
        return row, now

    @staticmethod
    def _public(row):
        return PublicCommercialApproval(snapshot=row.snapshot, snapshot_hash=row.snapshot_hash,
            recipient_name=row.recipient_name, expires_at=row.expires_at,
            status="CONFIRMED" if row.confirmed_at else "PENDING", confirmed_at=row.confirmed_at,
            confirmed_name=row.confirmed_name)

    @classmethod
    def preview(cls, uow, token):
        row, _ = cls._resolve(uow, token)
        return cls._public(row)

    @classmethod
    def request_code(cls, uow, token):
        from app.modules.accounting.application.approval_email import enqueue_code
        row, now = cls._resolve(uow, token)
        return request_code(uow, row, token, now, enqueue=enqueue_code)

    @classmethod
    def confirm(cls, uow, body, *, ip=None, user_agent=None):
        row, now = cls._resolve(uow, body.token)
        if (body.terms_version != row.snapshot["terms"]["version"] or body.price_version != row.snapshot["price"]["version"]
                or not compare_digest(body.snapshot_hash, row.snapshot_hash)):
            raise Conflict("Confirmation must match both displayed versions")
        if not verify_code(row, body.verification_code, now):
            return VerificationRejected()
        if row.confirmed_at:
            if body.signer_name != row.confirmed_name:
                raise Conflict("A factory decision is immutable")
            return cls._public(row)
        row.confirmed_at, row.mailbox_verified_at, row.confirmed_name = now, now, body.signer_name
        AuditService.add(uow, company_id=row.company_id, actor_user_id=None,
            entity_type="COMMERCIAL_APPROVAL", entity_id=row.id, action="CONFIRM", ip=ip, user_agent=user_agent,
            after={"actor_kind": "FACTORY_REPRESENTATIVE", "factory_contact_id": str(row.factory_contact_id),
                "terms_id": str(row.terms_id), "price_id": str(row.price_id), "snapshot_hash": row.snapshot_hash,
                "confirmed_name": row.confirmed_name, "mailbox_verified_at": now.isoformat(),
                "is_demo": row.snapshot["is_demo"], "usable_for_billing": False, "affects_earnings": False})
        return cls._public(row)
