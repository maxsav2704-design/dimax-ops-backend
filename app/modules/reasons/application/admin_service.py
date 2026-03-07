from __future__ import annotations

import uuid

from app.modules.reasons.domain.errors import ReasonCodeAlreadyExists
from app.modules.reasons.infrastructure.models import ReasonORM
from app.shared.domain.errors import NotFound


def normalize_code(raw: str) -> str:
    return raw.strip().lower()


class ReasonsAdminService:
    @staticmethod
    def create(
        uow,
        *,
        company_id: uuid.UUID,
        code: str,
        name: str,
        is_active: bool,
    ) -> ReasonORM:
        normalized = normalize_code(code)
        existing = uow.reasons.get_by_code(
            company_id=company_id,
            code=normalized,
            include_deleted=True,
        )
        if existing is not None:
            raise ReasonCodeAlreadyExists("reason code already exists")

        row = ReasonORM(
            company_id=company_id,
            code=normalized,
            name=name.strip(),
            is_active=is_active,
        )
        uow.reasons.save(row)
        uow.session.flush()
        return row

    @staticmethod
    def update(
        uow,
        *,
        company_id: uuid.UUID,
        reason_id: uuid.UUID,
        payload: dict,
    ) -> ReasonORM:
        row = uow.reasons.get(
            company_id=company_id,
            reason_id=reason_id,
        )
        if row is None:
            raise NotFound("Reason not found")

        if "code" in payload and payload["code"] is not None:
            new_code = normalize_code(payload["code"])
            if new_code != row.code:
                existing = uow.reasons.get_by_code(
                    company_id=company_id,
                    code=new_code,
                    include_deleted=True,
                )
                if existing is not None and existing.id != row.id:
                    raise ReasonCodeAlreadyExists("reason code already exists")
                row.code = new_code

        if "name" in payload and payload["name"] is not None:
            row.name = payload["name"].strip()

        if "is_active" in payload and payload["is_active"] is not None:
            row.is_active = bool(payload["is_active"])

        uow.reasons.save(row)
        return row

    @staticmethod
    def delete(
        uow,
        *,
        company_id: uuid.UUID,
        reason_id: uuid.UUID,
    ) -> None:
        row = uow.reasons.get(
            company_id=company_id,
            reason_id=reason_id,
        )
        if row is None:
            raise NotFound("Reason not found")
        uow.reasons.soft_delete(row)

