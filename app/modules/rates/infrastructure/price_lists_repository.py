from __future__ import annotations

from uuid import UUID
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM, UserORM
from app.modules.identity.domain.enums import UserRole
from app.modules.rates.infrastructure.price_list_models import FactoryPriceListItemORM, FactoryPriceListORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.modules.rates.infrastructure.reconciliation_queries import reconciliation_query
from app.modules.rates.infrastructure.application_check_queries import required_work_query
from app.modules.rates.infrastructure.timeline_models import FactoryPriceActivationORM


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

    def confirmed_approval(self, company_id: UUID, price_list_id: UUID):
        return self.session.scalar(select(FactoryPriceApprovalORM).where(
            FactoryPriceApprovalORM.company_id == company_id, FactoryPriceApprovalORM.price_list_id == price_list_id,
            FactoryPriceApprovalORM.confirmed_at.is_not(None)))

    def latest_confirmed_version(self, company_id: UUID):
        return self.session.scalar(select(func.max(FactoryPriceListORM.version)).where(
            FactoryPriceListORM.company_id == company_id, FactoryPriceListORM.status == "CONFIRMED")) or 0

    def required_work(self, company_id: UUID, price_list_id: UUID):
        return self.session.execute(required_work_query(company_id, price_list_id)).mappings().all()

    def can_activate_prices(self, company_id: UUID, actor_user_id: UUID) -> bool:
        return self.session.scalar(select(UserORM.id).join(
            AdminProfileORM, AdminProfileORM.user_id == UserORM.id,
        ).join(CompanyORM, CompanyORM.id == UserORM.company_id).where(
            UserORM.id == actor_user_id, UserORM.company_id == company_id,
            AdminProfileORM.company_id == company_id, UserORM.role == UserRole.ADMIN,
            UserORM.is_active.is_(True), UserORM.status == "ACTIVE", CompanyORM.is_active.is_(True),
            AdminProfileORM.admin_scope.in_(("OWNER", "OPERATIONS")),
            AdminProfileORM.can_view_rates.is_(True),
        )) is not None

    def activation_by_request(self, company_id: UUID, request_id: UUID):
        return self.session.scalar(select(FactoryPriceActivationORM).where(
            FactoryPriceActivationORM.company_id == company_id,
            FactoryPriceActivationORM.request_id == request_id,
        ))

    def latest_activation(self, company_id: UUID):
        return self.session.scalar(select(FactoryPriceActivationORM).where(
            FactoryPriceActivationORM.company_id == company_id,
        ).order_by(FactoryPriceActivationORM.effective_from.desc()).limit(1))

    def first_activation(self, company_id: UUID):
        return self.session.scalar(select(FactoryPriceActivationORM).where(
            FactoryPriceActivationORM.company_id == company_id,
        ).order_by(FactoryPriceActivationORM.effective_from).limit(1))

    def activation_at(self, company_id: UUID, performed_at: datetime):
        return self.session.scalar(select(FactoryPriceActivationORM).where(
            FactoryPriceActivationORM.company_id == company_id,
            FactoryPriceActivationORM.effective_from <= performed_at,
        ).order_by(FactoryPriceActivationORM.effective_from.desc()).limit(1))

    def first_confirmed_price_list(self, company_id: UUID):
        # Either header or decision evidence keeps the first version selected even if its other half is damaged.
        return self.session.scalar(select(FactoryPriceListORM).outerjoin(FactoryPriceApprovalORM,
            (FactoryPriceListORM.company_id == FactoryPriceApprovalORM.company_id)
            & (FactoryPriceListORM.id == FactoryPriceApprovalORM.price_list_id)
            & FactoryPriceApprovalORM.confirmed_at.is_not(None),
        ).where(FactoryPriceListORM.company_id == company_id,
            or_(FactoryPriceListORM.status == "CONFIRMED", FactoryPriceApprovalORM.confirmed_at.is_not(None)),
        ).order_by(FactoryPriceListORM.version).limit(1))

    def add_activation(self, row: FactoryPriceActivationORM):
        self.session.add(row)
        self.session.flush()
