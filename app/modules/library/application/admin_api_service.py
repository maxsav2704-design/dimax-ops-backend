from __future__ import annotations

import uuid

from app.modules.library.api.schemas import ProductLibraryItemDTO
from app.modules.library.infrastructure.models import ProductLibraryItemORM
from app.shared.domain.errors import Conflict, NotFound, ValidationError


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dto(item: ProductLibraryItemORM) -> ProductLibraryItemDTO:
    return ProductLibraryItemDTO(
        id=item.id,
        sku=item.sku,
        name_ru=item.name_ru,
        name_he=item.name_he,
        install_type=item.install_type,
        manufacturer=item.manufacturer,
        unit=item.unit,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


class ProductLibraryAdminApiService:
    @staticmethod
    def list_items(
        uow,
        *,
        company_id: uuid.UUID,
        q: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[ProductLibraryItemDTO]:
        normalized_status = _clean(status)
        if normalized_status is not None and normalized_status not in {"ACTIVE", "ARCHIVED"}:
            raise ValidationError("unsupported library status")
        rows = uow.product_library.list(
            company_id=company_id,
            q=_clean(q),
            status=normalized_status,
            limit=limit,
            offset=offset,
        )
        return [_dto(row) for row in rows]

    @staticmethod
    def create_item(
        uow,
        *,
        company_id: uuid.UUID,
        payload: dict,
    ) -> ProductLibraryItemDTO:
        sku = _clean(payload.get("sku"))
        if sku is None:
            raise ValidationError("sku is required")
        existing = uow.product_library.get_by_sku(company_id=company_id, sku=sku)
        if existing is not None:
            raise Conflict("Library SKU already exists", details={"sku": sku})

        item = ProductLibraryItemORM(
            company_id=company_id,
            sku=sku,
            name_ru=_clean(payload.get("name_ru")) or sku,
            name_he=_clean(payload.get("name_he")) or sku,
            install_type=_clean(payload.get("install_type")) or sku,
            manufacturer=_clean(payload.get("manufacturer")),
            unit=_clean(payload.get("unit")) or "piece",
            status=_clean(payload.get("status")) or "ACTIVE",
        )
        uow.product_library.save(item)
        uow.session.flush()
        return _dto(item)

    @staticmethod
    def update_item(
        uow,
        *,
        company_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: dict,
    ) -> ProductLibraryItemDTO:
        item = uow.product_library.get(company_id=company_id, item_id=item_id)
        if item is None:
            raise NotFound("Library item not found", details={"item_id": str(item_id)})

        if "sku" in payload:
            sku = _clean(payload.get("sku"))
            if sku is None:
                raise ValidationError("sku is required")
            existing = uow.product_library.get_by_sku(company_id=company_id, sku=sku)
            if existing is not None and existing.id != item.id:
                raise Conflict("Library SKU already exists", details={"sku": sku})
            item.sku = sku

        for field in ("name_ru", "name_he", "install_type"):
            if field in payload:
                value = _clean(payload.get(field))
                if value is None:
                    raise ValidationError(f"{field} is required")
                setattr(item, field, value)

        if "manufacturer" in payload:
            item.manufacturer = _clean(payload.get("manufacturer"))
        if "unit" in payload and payload.get("unit") is not None:
            item.unit = str(payload["unit"])
        if "status" in payload and payload.get("status") is not None:
            item.status = str(payload["status"])

        uow.product_library.save(item)
        uow.session.flush()
        return _dto(item)
