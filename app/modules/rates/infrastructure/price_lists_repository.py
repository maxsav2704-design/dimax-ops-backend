from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.rates.infrastructure.price_list_models import FactoryPriceListItemORM, FactoryPriceListORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.modules.rates.infrastructure.reconciliation_queries import reconciliation_query


class FactoryPriceListsRepository:
    def __init__(self, session: Session):
        self.session = session

    def lock_company(self, company_id: UUID) -> bool:
        return self.session.scalar(
            select(CompanyORM.id).where(CompanyORM.id == company_id).with_for_update()
        ) is not None

    def get(self, company_id: UUID, price_list_id: UUID):
        return self.session.scalar(select(FactoryPriceListORM).where(
            FactoryPriceListORM.company_id == company_id, FactoryPriceListORM.id == price_list_id,
        ))

    def by_request(self, company_id: UUID, request_id: UUID):
        return self.session.scalar(select(FactoryPriceListORM).where(
            FactoryPriceListORM.company_id == company_id, FactoryPriceListORM.request_id == request_id,
        ))

    def latest_version(self, company_id: UUID) -> int:
        return self.session.scalar(select(func.max(FactoryPriceListORM.version)).where(
            FactoryPriceListORM.company_id == company_id,
        )) or 0

    def page(self, company_id: UUID, limit: int, offset: int):
        scope = FactoryPriceListORM.company_id == company_id
        total = self.session.scalar(select(func.count()).select_from(FactoryPriceListORM).where(scope))
        rows = self.session.scalars(select(FactoryPriceListORM).where(scope).order_by(
            FactoryPriceListORM.version.desc(),
        ).limit(limit).offset(offset)).all()
        return rows, total

    def items(self, company_id: UUID, price_list_id: UUID):
        return self.session.scalars(select(FactoryPriceListItemORM).where(
            FactoryPriceListItemORM.company_id == company_id,
            FactoryPriceListItemORM.price_list_id == price_list_id,
        ).order_by(FactoryPriceListItemORM.kind, FactoryPriceListItemORM.name,
                   FactoryPriceListItemORM.id)).all()

    def catalog(self, company_id: UUID, kind: str, ids: set[UUID]):
        model = DoorTypeORM if kind == "DOOR" else AddonTypeORM
        rows = self.session.scalars(select(model).where(
            model.company_id == company_id, model.id.in_(ids), model.is_active.is_(True),
            model.deleted_at.is_(None),
        )).all()
        return {row.id: row for row in rows}

    def add(self, row: FactoryPriceListORM, items: list[FactoryPriceListItemORM]):
        self.session.add(row)
        self.session.flush()
        self.session.add_all(items)
        self.session.flush()

    def company(self, company_id: UUID):
        return self.session.get(CompanyORM, company_id, populate_existing=True)

    def approval_scope(self, token_hash: str):
        return self.session.execute(select(FactoryPriceApprovalORM.id, FactoryPriceApprovalORM.company_id).where(
            FactoryPriceApprovalORM.token_hash == token_hash,
        )).first()

    def approval(self, company_id: UUID, approval_id: UUID):
        return self.session.scalar(select(FactoryPriceApprovalORM).where(
            FactoryPriceApprovalORM.company_id == company_id, FactoryPriceApprovalORM.id == approval_id,
        ).execution_options(populate_existing=True))

    def approval_page(self, company_id: UUID, price_list_id: UUID, limit: int, offset: int):
        scope = (FactoryPriceApprovalORM.company_id == company_id,
                 FactoryPriceApprovalORM.price_list_id == price_list_id)
        total = self.session.scalar(select(func.count()).select_from(FactoryPriceApprovalORM).where(*scope))
        rows = self.session.scalars(select(FactoryPriceApprovalORM).where(*scope).order_by(
            FactoryPriceApprovalORM.created_at.desc(), FactoryPriceApprovalORM.id,
        ).limit(limit).offset(offset)).all()
        return rows, total

    def pending_approvals(self, company_id: UUID, price_list_id: UUID):
        return self.session.scalars(select(FactoryPriceApprovalORM).where(
            FactoryPriceApprovalORM.company_id == company_id,
            FactoryPriceApprovalORM.price_list_id == price_list_id,
            FactoryPriceApprovalORM.revoked_at.is_(None), FactoryPriceApprovalORM.confirmed_at.is_(None),
        )).all()

    def add_approval(self, row: FactoryPriceApprovalORM):
        self.session.flush()
        self.session.add(row)
        self.session.flush()

    def reconciliation_page(self, **scope):
        return self.session.execute(reconciliation_query(**scope)).mappings().all()
