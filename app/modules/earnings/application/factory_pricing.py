from datetime import timezone
from decimal import Decimal

from app.modules.earnings.infrastructure.factory_price_models import FactoryEarningPriceORM
from app.modules.earnings.infrastructure.work_price_models import WorkPriceAccrualORM
from app.modules.earnings.application.work_pricing import ApprovedWorkPrice
from app.modules.rates.application.timeline_service import FactoryPriceTimelineService
from app.shared.domain.errors import Conflict, NotFound


class FactoryEarningsPricing:
    @staticmethod
    def lock_company(uow, company_id):
        # Acquire before project/door/ledger locks, including in the legacy mode at cutover.
        if not uow.price_lists.lock_company(company_id):
            raise NotFound("Company not found")

    @staticmethod
    def is_active(uow, company_id):
        return uow.price_lists.latest_activation(company_id) is not None

    @staticmethod
    def quote(uow, *, company_id, kind, target_id, performed_at, legacy_queue=False, seen_price_list_id=None,
              approved_work_price: ApprovedWorkPrice | None = None):
        if approved_work_price is not None:
            approved_work_price.validate_target(company_id=company_id, kind=kind, target_id=target_id,
                                                performed_at=performed_at)
            return approved_work_price
        if seen_price_list_id is None and not FactoryEarningsPricing.is_active(uow, company_id):
            return None
        if performed_at.tzinfo is None:
            performed_at = performed_at.replace(tzinfo=timezone.utc)
        return FactoryPriceTimelineService.quote(uow, company_id=company_id, kind=kind, target_id=target_id,
                                                performed_at=performed_at, legacy_queue=legacy_queue,
                                                seen_price_list_id=seen_price_list_id)

    @staticmethod
    def evidence(uow, company_id, work_id):
        return uow.session.query(FactoryEarningPriceORM).filter_by(
            company_id=company_id, completed_work_id=work_id).one_or_none()

    @staticmethod
    def attach(uow, work, quote):
        if quote is None:
            return
        if isinstance(quote, ApprovedWorkPrice):
            # The resolving service writes immutable evidence and queue ACK in this same UOW.
            quote.validate_work(work)
            return
        if (work.work_kind != quote.kind or work.entry_type != "ORIGINAL"
                or Decimal(str(work.rate_snapshot)) != quote.rate
                or Decimal(str(work.amount_snapshot)) != quote.amount(work.quantity)):
            raise Conflict("Earning does not match the confirmed factory price", field="price_list_id")
        uow.session.flush()
        uow.session.add(FactoryEarningPriceORM(company_id=work.company_id, completed_work_id=work.id,
            price_list_id=quote.price_list_id, price_list_item_id=quote.price_list_item_id,
            approval_id=quote.approval_id, activation_id=quote.activation_id, version=quote.version,
            selection=quote.selection, unit=quote.unit, currency=quote.currency, confirmed_rate=quote.rate,
            snapshot_hash=quote.snapshot_hash, performed_at=quote.performed_at, effective_from=quote.effective_from))
        uow.session.flush()

    @staticmethod
    def copy_reversal(uow, original, reversal):
        proof = FactoryEarningsPricing.evidence(uow, original.company_id, original.id)
        work_proof = uow.session.query(WorkPriceAccrualORM).filter_by(
            company_id=original.company_id, completed_work_id=original.id).one_or_none()
        if proof is None and work_proof is None:
            return
        if (reversal.company_id != original.company_id or reversal.entry_type != "REVERSAL"
                or reversal.correction_ref_id != original.id or reversal.quantity != original.quantity
                or reversal.rate_snapshot != -original.rate_snapshot or reversal.amount_snapshot != -original.amount_snapshot):
            raise Conflict("Reversal must exactly offset its original earning")
        if proof is None:
            # An exact reversal retains its immutable basis through correction_ref_id.
            return
        values = {col.name: getattr(proof, col.name) for col in FactoryEarningPriceORM.__table__.columns
                  if col.name not in {"completed_work_id", "created_at"}}
        uow.session.flush()
        uow.session.add(FactoryEarningPriceORM(completed_work_id=reversal.id, **values))
        uow.session.flush()
