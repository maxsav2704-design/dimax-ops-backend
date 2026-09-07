from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.library.infrastructure.models import ProductLibraryItemORM


class ProductLibraryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self,
        *,
        company_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> ProductLibraryItemORM | None:
        stmt = select(ProductLibraryItemORM).where(
            ProductLibraryItemORM.company_id == company_id,
            ProductLibraryItemORM.id == item_id,
        )
        return self.session.execute(stmt).scalars().first()

    def get_by_sku(
        self,
        *,
        company_id: uuid.UUID,
        sku: str,
    ) -> ProductLibraryItemORM | None:
        stmt = select(ProductLibraryItemORM).where(
            ProductLibraryItemORM.company_id == company_id,
            ProductLibraryItemORM.sku == sku,
        )
        return self.session.execute(stmt).scalars().first()

    def list(
        self,
        *,
        company_id: uuid.UUID,
        q: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[ProductLibraryItemORM]:
        stmt = select(ProductLibraryItemORM).where(
            ProductLibraryItemORM.company_id == company_id
        )
        if status:
            stmt = stmt.where(ProductLibraryItemORM.status == status)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    ProductLibraryItemORM.sku.ilike(like),
                    ProductLibraryItemORM.name_ru.ilike(like),
                    ProductLibraryItemORM.name_he.ilike(like),
                    ProductLibraryItemORM.install_type.ilike(like),
                    ProductLibraryItemORM.manufacturer.ilike(like),
                )
            )
        stmt = (
            stmt.order_by(ProductLibraryItemORM.status.asc(), ProductLibraryItemORM.sku.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars().all())

    def save(self, item: ProductLibraryItemORM) -> None:
        self.session.add(item)
