"""Read-only period estimate: signed journal lines of a period valued at the commercial rate in effect.

Preliminary figures for the OWNER. Nothing is reserved, claimed, exported or invoiced here;
VAT is not computed until the accountant confirms the rate and the tax moment.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select

from app.modules.accounting.application.agreement_dto import PeriodDetail, PeriodLine, PeriodPage, PeriodSummary
from app.modules.accounting.application.agreement_service import (
    CommercialAgreementRepository, CommercialAgreementService, CommercialRateResolver,
)
from app.modules.accounting.application.approval_service import CommercialApprovalService
from app.modules.accounting.domain.periods import CUTOVER, Period, local_day, period_for_day, period_from_key, periods_between
from app.modules.journal.infrastructure.models import JournalAddonItemORM, JournalDoorItemORM, JournalORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.shared.domain.errors import Conflict, NotFound
from app.shared.infrastructure.db.base import utcnow

CENT = Decimal("0.01")


class CommercialEstimateService:
    @staticmethod
    def _guard(uow, user, contract_id: UUID):
        if not CommercialAgreementService.enabled():
            raise Conflict("Commercial activation is not enabled on this server")
        return CommercialApprovalService._owner(uow, user, contract_id)

    @staticmethod
    def _signed_lines(session, company_id: UUID):
        """Every dated line of every signed journal: (journal_id, project_name, kind, target_id, label, unit, qty, local day)."""
        journals = session.execute(select(JournalORM.id, ProjectORM.name).join(ProjectORM, ProjectORM.id == JournalORM.project_id)
                                   .where(JournalORM.company_id == company_id, JournalORM.signed_at.is_not(None))).all()
        if not journals:
            return [], 0
        names = {row.id: row.name for row in journals}
        ids = list(names)
        lines, undated = [], 0
        for item in session.scalars(select(JournalDoorItemORM).where(JournalDoorItemORM.journal_id.in_(ids))).all():
            if item.installed_at is None:
                undated += 1
                continue
            lines.append((item.journal_id, names[item.journal_id], "INSTALLATION", item.door_type_id, item.unit_label,
                          None, Decimal("1"), local_day(item.installed_at)))
        for item in session.scalars(select(JournalAddonItemORM).where(JournalAddonItemORM.journal_id.in_(ids))).all():
            lines.append((item.journal_id, names[item.journal_id], "ADDON", item.addon_type_id, item.addon_name,
                          item.unit, Decimal(item.qty_done), local_day(item.done_at)))
        return lines, undated

    @classmethod
    def _compute(cls, session, contract, period: Period, lines, *, with_lines: bool):
        repo = CommercialAgreementRepository(session)
        blocked = "MULTIPLE_CONTRACTS" if repo.other_contracts_in_effect(
            contract.company_id, contract.id, period.start, period.end) else None
        in_period = [line for line in lines if period.contains(line[7])]
        journals = {line[0] for line in in_period}
        rated, unrated, amount, detail, basis = 0, 0, Decimal("0"), [], {}
        if blocked is None:
            for journal_id, project, kind, target, label, unit, qty, day in in_period:
                agreement = CommercialRateResolver.agreement_on(session, contract.company_id, contract.id, day)
                rate = None
                if agreement is None:
                    reason = "NO_AGREEMENT"
                elif basis.setdefault(agreement.id, cls._basis(session, agreement)) == "STAGES":
                    # Owner's decision 2026-10-23: stage contracts wait for stage facts, no interim full-installation estimate.
                    reason = "STAGES_NOT_SUPPORTED"
                else:
                    rate = CommercialRateResolver.rate_for(session, contract.company_id, contract.id, kind=kind,
                                                           target_id=target, on_date=day)
                    reason = "RATED" if rate is not None else "NO_RATE"
                line_amount = None
                if reason == "RATED":
                    line_amount = (qty * rate.unit_price_ex_vat).quantize(CENT, rounding=ROUND_HALF_UP)
                    amount += line_amount
                    rated += 1
                else:
                    unrated += 1
                if with_lines:
                    detail.append(PeriodLine(
                        journal_id=journal_id, project_name=project, kind=kind, label=label, work_date=day, quantity=qty,
                        unit=(rate.unit if rate else unit), unit_price_ex_vat=rate.unit_price_ex_vat if reason == "RATED" else None,
                        amount_ex_vat=line_amount, price_version=rate.price_version if reason == "RATED" else None,
                        agreement_id=agreement.id if agreement else None, reason=reason))
        summary = dict(start=period.start, end=period.end, signed_journals=len(journals), rated_lines=rated,
                       unrated_lines=unrated, amount_ex_vat=amount.quantize(CENT), blocked_reason=blocked)
        return PeriodDetail(**summary, lines=detail) if with_lines else PeriodSummary(**summary)

    @staticmethod
    def _basis(session, agreement) -> str:
        from app.modules.accounting.infrastructure.models import CommercialContractTermsORM
        return session.get(CommercialContractTermsORM, agreement.terms_id).billing_basis

    @classmethod
    def periods(cls, uow, user, contract_id: UUID) -> PeriodPage:
        _, contract = cls._guard(uow, user, contract_id)
        today = local_day(utcnow())
        lines, undated = cls._signed_lines(uow.session, user.company_id)
        # Before the accounting start the first period is already listed, so the office sees where lines will land.
        periods = periods_between(CUTOVER, max(today, CUTOVER))
        items = [cls._compute(uow.session, contract, period, lines, with_lines=False) for period in reversed(periods)]
        return PeriodPage(items=items, cutover=CUTOVER, today=today, current_start=period_for_day(max(today, CUTOVER)).start,
                          undated_lines=undated, activation_enabled=True)

    @classmethod
    def period(cls, uow, user, contract_id: UUID, key: str) -> PeriodDetail:
        _, contract = cls._guard(uow, user, contract_id)
        try:
            period = period_from_key(key)
        except ValueError as exc:
            raise NotFound("Period not found") from exc
        today = local_day(utcnow())
        if period.start < CUTOVER or period.start > max(today, CUTOVER):
            raise NotFound("Period not found")
        lines, _ = cls._signed_lines(uow.session, user.company_id)
        return cls._compute(uow.session, contract, period, lines, with_lines=True)
