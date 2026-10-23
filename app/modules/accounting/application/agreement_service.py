"""Putting a factory-confirmed pair into effect, and resolving the commercial rate on a date.

In effect means: from this date the factory-to-DIMAX rate of this pair applies to new work.
It does not create a claim, an invoice, a payment or an installer earning, and it never
recalculates anything already recorded.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.modules.accounting.application.agreement_dto import (
    ActivateCommercialAgreement, CommercialAgreementPage, CommercialAgreementSummary,
)
from app.modules.accounting.application.approval_service import CommercialApprovalService
from app.modules.accounting.application.service import _fingerprint
from app.modules.accounting.domain.periods import CUTOVER, local_day
from app.modules.accounting.infrastructure.agreement_models import CommercialAgreementORM as Agreement
from app.modules.accounting.infrastructure.models import (
    CommercialContractORM, CommercialContractTermsORM, CommercialPriceItemORM, CommercialPriceVersionORM,
)
from app.modules.audit.application.service import AuditService
from app.shared.domain.errors import Conflict, NotFound, ValidationError
from app.shared.infrastructure.db.base import utcnow


def _test_env() -> bool:
    return os.environ.get("APP_ENV", "").lower() == "test"


class CommercialAgreementRepository:
    def __init__(self, session):
        self.session = session

    def lock_contract(self, company_id: UUID, contract_id: UUID) -> None:
        # Activations of one contract are serialized; the partial unique index backs this up.
        self.session.execute(select(CommercialContractORM.id).where(
            CommercialContractORM.company_id == company_id, CommercialContractORM.id == contract_id,
        ).with_for_update())

    def request(self, company_id: UUID, request_id: UUID):
        return self.session.scalar(select(Agreement).where(Agreement.company_id == company_id, Agreement.request_id == request_id))

    def for_approval(self, approval_id: UUID) -> UUID | None:
        return self.session.scalar(select(Agreement.id).where(Agreement.approval_id == approval_id))

    def open(self, company_id: UUID, contract_id: UUID):
        return self.session.scalar(select(Agreement).where(
            Agreement.company_id == company_id, Agreement.contract_id == contract_id, Agreement.effective_until.is_(None),
        ).with_for_update())

    def on_day(self, company_id: UUID, contract_id: UUID, day):
        return self.session.scalar(select(Agreement).where(
            Agreement.company_id == company_id, Agreement.contract_id == contract_id,
            Agreement.effective_from <= day,
            (Agreement.effective_until.is_(None)) | (Agreement.effective_until >= day),
        ))

    def page(self, company_id: UUID, contract_id: UUID, limit: int, offset: int):
        scope = (Agreement.company_id == company_id, Agreement.contract_id == contract_id)
        rows = self.session.scalars(select(Agreement).where(*scope).order_by(Agreement.effective_from.desc(), Agreement.id)
                                    .limit(limit).offset(offset)).all()
        total = self.session.scalar(select(func.count()).select_from(Agreement).where(*scope))
        return rows, total

    def other_contracts_in_effect(self, company_id: UUID, contract_id: UUID, start, end) -> int:
        """How many OTHER contracts of the company have an agreement touching [start, end]."""
        return self.session.scalar(select(func.count(func.distinct(Agreement.contract_id))).where(
            Agreement.company_id == company_id, Agreement.contract_id != contract_id,
            Agreement.effective_from <= end,
            (Agreement.effective_until.is_(None)) | (Agreement.effective_until >= start),
        )) or 0

    def item(self, company_id: UUID, price_id: UUID, kind: str, target_id: UUID, stage_code: str = ""):
        target = CommercialPriceItemORM.addon_type_id if kind == "ADDON" else CommercialPriceItemORM.door_type_id
        return self.session.scalar(select(CommercialPriceItemORM).where(
            CommercialPriceItemORM.company_id == company_id, CommercialPriceItemORM.price_version_id == price_id,
            CommercialPriceItemORM.kind == kind, target == target_id, CommercialPriceItemORM.stage_code == stage_code,
        ))

    def add(self, row) -> None:
        self.session.add(row)
        self.session.flush()


@dataclass(frozen=True)
class ResolvedRate:
    unit_price_ex_vat: Decimal
    unit: str
    name: str
    price_id: UUID
    price_version: int
    terms_id: UUID
    billing_basis: str
    agreement_id: UUID
    approval_id: UUID


class CommercialRateResolver:
    """The factory-to-DIMAX rate in effect on a date. No agreement or no position means None, never a default price."""

    @staticmethod
    def agreement_on(session, company_id: UUID, contract_id: UUID, day):
        contract = session.get(CommercialContractORM, contract_id)
        if contract is None or contract.company_id != company_id or (contract.is_demo and not _test_env()):
            return None
        return CommercialAgreementRepository(session).on_day(company_id, contract_id, day)

    @classmethod
    def rate_for(cls, session, company_id: UUID, contract_id: UUID, *, kind: str, target_id: UUID, on_date,
                 stage_code: str = "") -> ResolvedRate | None:
        agreement = cls.agreement_on(session, company_id, contract_id, on_date)
        if agreement is None:
            return None
        repo = CommercialAgreementRepository(session)
        item = repo.item(company_id, agreement.price_id, kind, target_id, stage_code)
        if item is None:
            return None
        price = session.get(CommercialPriceVersionORM, agreement.price_id)
        terms = session.get(CommercialContractTermsORM, agreement.terms_id)
        return ResolvedRate(unit_price_ex_vat=item.unit_price_ex_vat, unit=item.unit, name=item.name,
                            price_id=price.id, price_version=price.version, terms_id=terms.id,
                            billing_basis=terms.billing_basis, agreement_id=agreement.id, approval_id=agreement.approval_id)


class CommercialAgreementService:
    @staticmethod
    def enabled() -> bool:
        return bool(settings.COMMERCIAL_ACTIVATION_ENABLED)

    @staticmethod
    def _status(row, today) -> str:
        if row.effective_until is not None and row.effective_until < today:
            return "ENDED"
        if row.effective_from > today:
            return "SCHEDULED"
        return "ACTIVE"

    @classmethod
    def _summary(cls, uow, row, contract, today) -> CommercialAgreementSummary:
        terms = uow.session.get(CommercialContractTermsORM, row.terms_id)
        price = uow.session.get(CommercialPriceVersionORM, row.price_id)
        fields = {key: getattr(row, key) for key in CommercialAgreementSummary.model_fields if hasattr(row, key)}
        return CommercialAgreementSummary(**fields, terms_version=terms.version, price_version=price.version,
                                          billing_basis=terms.billing_basis, status=cls._status(row, today), is_demo=contract.is_demo)

    @classmethod
    def page(cls, uow, user, contract_id: UUID, limit: int = 20, offset: int = 0) -> CommercialAgreementPage:
        _, contract = CommercialApprovalService._owner(uow, user, contract_id)
        repo = CommercialAgreementRepository(uow.session)
        today = local_day(utcnow())
        rows, total = repo.page(user.company_id, contract_id, limit, offset)
        current = repo.on_day(user.company_id, contract_id, today)
        return CommercialAgreementPage(items=[cls._summary(uow, row, contract, today) for row in rows], total=total,
                                       activation_enabled=cls.enabled(), cutover=CUTOVER, today=today,
                                       current=cls._summary(uow, current, contract, today) if current else None)

    @classmethod
    def activate(cls, uow, user, contract_id: UUID, body: ActivateCommercialAgreement) -> CommercialAgreementSummary:
        if not cls.enabled():
            raise Conflict("Commercial activation is not enabled on this server")
        approvals, contract = CommercialApprovalService._owner(uow, user, contract_id)
        repo = CommercialAgreementRepository(uow.session)
        repo.lock_contract(user.company_id, contract_id)
        today = local_day(utcnow())
        fingerprint = _fingerprint({"contract_id": str(contract_id), "actor": str(user.id),
                                    **body.model_dump(mode="json", exclude={"request_id"})})
        previous = repo.request(user.company_id, body.request_id)
        if previous:
            if previous.request_fingerprint != fingerprint:
                raise Conflict("Request ID already used for another activation")
            return cls._summary(uow, previous, contract, today)
        approval = approvals.get(user.company_id, contract_id, body.approval_id)
        if approval is None:
            raise NotFound("Factory decision not found")
        if approval.confirmed_at is None or approval.revoked_at is not None:
            raise Conflict("Only a pair confirmed by the factory can be put into effect")
        if contract.is_demo and not _test_env():
            raise Conflict("Demo contracts never enter real accounting")
        terms = approvals.terms_version(user.company_id, contract_id, approval.terms_id)
        price = approvals.price(user.company_id, contract_id, approval.price_id)
        if body.effective_from < CUTOVER:
            raise ValidationError(f"The effective date cannot precede the accounting start {CUTOVER.isoformat()}",
                                  field="effective_from")
        if body.effective_from < max(terms.proposed_from, price.proposed_from):
            raise ValidationError("The effective date precedes the proposed dates of the confirmed versions",
                                  field="effective_from")
        if terms.proposed_until is not None and body.effective_from > terms.proposed_until:
            raise ValidationError("The effective date is after the proposed end of the confirmed terms",
                                  field="effective_from")
        if repo.for_approval(approval.id) is not None:
            raise Conflict("These exact versions are already in effect")
        open_row = repo.open(user.company_id, contract_id)
        closed = None
        if open_row is not None:
            if open_row.effective_from >= body.effective_from:
                raise Conflict("The new effective date must be later than the start of the agreement in effect")
            open_row.effective_until = body.effective_from - timedelta(days=1)
            closed = open_row
            uow.session.flush()
        row = Agreement(id=uuid4(), company_id=user.company_id, contract_id=contract_id, terms_id=approval.terms_id,
                        price_id=approval.price_id, approval_id=approval.id, request_id=body.request_id,
                        effective_from=body.effective_from, effective_until=None, activated_by=user.id,
                        activated_by_name=approvals.actor_name(user.company_id, user.id) or "OWNER",
                        activated_at=utcnow(), reason=body.reason, request_fingerprint=fingerprint,
                        snapshot_hash=approval.snapshot_hash)
        try:
            repo.add(row)
        except IntegrityError as exc:
            # Overlap or a concurrent activation refused by the database guards.
            raise Conflict("Commercial agreements of one contract cannot overlap") from exc
        AuditService.add(uow, company_id=user.company_id, actor_user_id=user.id,
                         entity_type="COMMERCIAL_AGREEMENT", entity_id=row.id, action="ACTIVATE", reason=body.reason[:500],
                         before={"closed_agreement_id": str(closed.id), "closed_until": closed.effective_until.isoformat()} if closed else None,
                         after={"contract_id": str(contract_id), "approval_id": str(approval.id), "terms_id": str(row.terms_id),
                                "price_id": str(row.price_id), "effective_from": row.effective_from.isoformat(),
                                "snapshot_hash": row.snapshot_hash, "is_demo": contract.is_demo,
                                "creates_claim": False, "affects_earnings": False})
        return cls._summary(uow, row, contract, today)
