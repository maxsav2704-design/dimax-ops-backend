from sqlalchemy import func, select

from app.modules.accounting.infrastructure.approval_models import CommercialApprovalORM as Approval
from app.modules.accounting.infrastructure.repositories import CommercialDraftRepository
from app.modules.outbox.infrastructure.models import OutboxMessageORM


class CommercialApprovalRepository(CommercialDraftRepository):
    def request(self, company_id, request_id):
        return self.session.scalar(select(Approval).where(Approval.company_id == company_id, Approval.request_id == request_id))

    def get(self, company_id, contract_id, approval_id):
        return self.session.scalar(select(Approval).where(Approval.company_id == company_id,
            Approval.contract_id == contract_id, Approval.id == approval_id))

    def scope(self, token_hash):
        return self.session.execute(select(Approval.company_id, Approval.contract_id, Approval.id)
            .where(Approval.token_hash == token_hash)).one_or_none()

    def pending(self, company_id, contract_id):
        return self.session.scalars(select(Approval).where(Approval.company_id == company_id,
            Approval.contract_id == contract_id, Approval.revoked_at.is_(None), Approval.confirmed_at.is_(None))).all()

    def confirmed_pair(self, company_id, terms_id, price_id):
        return self.session.scalar(select(Approval.id).where(Approval.company_id == company_id,
            Approval.terms_id == terms_id, Approval.price_id == price_id, Approval.confirmed_at.is_not(None)))

    def page(self, company_id, contract_id, limit, offset):
        scope = (Approval.company_id == company_id, Approval.contract_id == contract_id)
        rows = self.session.scalars(select(Approval).where(*scope).order_by(Approval.created_at.desc(), Approval.id)
            .limit(limit).offset(offset)).all()
        total = self.session.scalar(select(func.count()).select_from(Approval).where(*scope))
        return rows, total

    def delivery_status(self, row):
        return self.session.scalar(select(OutboxMessageORM.status).where(
            OutboxMessageORM.company_id == row.company_id, OutboxMessageORM.id == row.email_outbox_id))
