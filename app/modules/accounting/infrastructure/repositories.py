from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounting.infrastructure.models import (
    CommercialContractORM, CommercialContractTermsORM, CommercialPriceItemORM, CommercialPriceVersionORM,
)
from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM, UserORM


class CommercialDraftRepository:
    def __init__(self, session: Session):
        self.session = session

    def owner_is_active(self, company_id: UUID, actor_id: UUID) -> bool:
        return self.session.scalar(
            select(UserORM.id).join(AdminProfileORM, AdminProfileORM.user_id == UserORM.id)
            .join(CompanyORM, CompanyORM.id == UserORM.company_id)
            .where(UserORM.company_id == company_id, UserORM.id == actor_id,
                   UserORM.is_active.is_(True), UserORM.status == "ACTIVE", UserORM.role == "ADMIN",
                   CompanyORM.is_active.is_(True), AdminProfileORM.company_id == company_id,
                   AdminProfileORM.admin_scope == "OWNER")
            .with_for_update(read=True, of=(UserORM, AdminProfileORM))
        ) is not None

    def lock_company(self, company_id: UUID) -> bool:
        return self.session.scalar(select(CompanyORM.id).where(
            CompanyORM.id == company_id, CompanyORM.is_active.is_(True),
        ).with_for_update(key_share=True)) is not None

    def contract(self, company_id: UUID, contract_id: UUID):
        return self.session.scalar(select(CommercialContractORM).where(
            CommercialContractORM.company_id == company_id, CommercialContractORM.id == contract_id,
        ))

    def contract_request(self, company_id: UUID, request_id: UUID):
        return self.session.scalar(select(CommercialContractORM).where(
            CommercialContractORM.company_id == company_id, CommercialContractORM.request_id == request_id,
        ))

    def contract_reference_exists(self, company_id: UUID, reference: str) -> bool:
        return self.session.scalar(select(CommercialContractORM.id).where(
            CommercialContractORM.company_id == company_id, CommercialContractORM.reference == reference,
        )) is not None

    def contracts(self, company_id: UUID, limit: int, offset: int):
        scope = CommercialContractORM.company_id == company_id
        rows = self.session.scalars(select(CommercialContractORM).where(scope).order_by(
            CommercialContractORM.created_at.desc(), CommercialContractORM.id,
        ).limit(limit).offset(offset)).all()
        total = self.session.scalar(select(func.count()).select_from(CommercialContractORM).where(scope))
        return rows, total

    def price_request(self, company_id: UUID, request_id: UUID):
        return self.session.scalar(select(CommercialPriceVersionORM).where(
            CommercialPriceVersionORM.company_id == company_id, CommercialPriceVersionORM.request_id == request_id,
        ))

    def terms_request(self, company_id: UUID, request_id: UUID):
        return self.session.scalar(select(CommercialContractTermsORM).where(
            CommercialContractTermsORM.company_id == company_id, CommercialContractTermsORM.request_id == request_id,
        ))

    def terms_version(self, company_id: UUID, contract_id: UUID, terms_id: UUID):
        return self.session.scalar(select(CommercialContractTermsORM).where(
            CommercialContractTermsORM.company_id == company_id,
            CommercialContractTermsORM.contract_id == contract_id, CommercialContractTermsORM.id == terms_id,
        ))

    def terms(self, company_id: UUID, contract_id: UUID, limit: int, offset: int):
        scope = (CommercialContractTermsORM.company_id == company_id,
                 CommercialContractTermsORM.contract_id == contract_id)
        rows = self.session.scalars(select(CommercialContractTermsORM).where(*scope).order_by(
            CommercialContractTermsORM.version.desc(),
        ).limit(limit).offset(offset)).all()
        total, latest = self.session.execute(select(
            func.count(), func.coalesce(func.max(CommercialContractTermsORM.version), 0),
        ).where(*scope)).one()
        return rows, total, latest

    def actor_name(self, company_id: UUID, user_id: UUID):
        return self.session.scalar(select(UserORM.full_name).where(
            UserORM.company_id == company_id, UserORM.id == user_id,
        ))

    def price(self, company_id: UUID, contract_id: UUID, price_id: UUID):
        return self.session.scalar(select(CommercialPriceVersionORM).where(
            CommercialPriceVersionORM.company_id == company_id,
            CommercialPriceVersionORM.contract_id == contract_id, CommercialPriceVersionORM.id == price_id,
        ))

    def prices(self, company_id: UUID, contract_id: UUID, limit: int, offset: int):
        scope = (CommercialPriceVersionORM.company_id == company_id,
                 CommercialPriceVersionORM.contract_id == contract_id)
        rows = self.session.scalars(select(CommercialPriceVersionORM).where(*scope).order_by(
            CommercialPriceVersionORM.version.desc(),
        ).limit(limit).offset(offset)).all()
        total, latest = self.session.execute(select(
            func.count(), func.coalesce(func.max(CommercialPriceVersionORM.version), 0),
        ).where(*scope)).one()
        return rows, total, latest

    def items(self, company_id: UUID, price_id: UUID):
        return self.session.scalars(select(CommercialPriceItemORM).where(
            CommercialPriceItemORM.company_id == company_id,
            CommercialPriceItemORM.price_version_id == price_id,
        ).order_by(CommercialPriceItemORM.kind, CommercialPriceItemORM.name,
                   CommercialPriceItemORM.stage_code, CommercialPriceItemORM.id)).all()

    def catalog(self, company_id: UUID, kind: str, ids: set[UUID]):
        model = AddonTypeORM if kind == "ADDON" else DoorTypeORM
        return {row.id: row for row in self.session.scalars(select(model).where(
            model.company_id == company_id, model.id.in_(ids),
            model.deleted_at.is_(None), model.is_active.is_(True),
        )).all()}

    def add(self, row) -> None:
        self.session.add(row)
        self.session.flush()
