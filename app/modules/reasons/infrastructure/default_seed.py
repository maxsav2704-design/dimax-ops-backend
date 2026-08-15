from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.reasons.infrastructure.models import ReasonORM


@dataclass(frozen=True)
class DefaultReason:
    code: str
    name: str


DEFAULT_REASONS: tuple[DefaultReason, ...] = (
    DefaultReason("blocked_opening", "Blocked opening"),
    DefaultReason("site_not_ready", "Site not ready"),
    DefaultReason("no_site_access", "No site or apartment access"),
    DefaultReason("door_not_on_site", "Door not delivered to site"),
    DefaultReason("wrong_door_supplied", "Wrong door supplied"),
    DefaultReason("damaged_door", "Door damaged"),
    DefaultReason("size_mismatch", "Size or opening mismatch"),
    DefaultReason("missing_hardware", "Missing hardware or parts"),
    DefaultReason("client_hold", "Client or developer hold"),
    DefaultReason("safety_blocker", "Safety blocker"),
)


def seed_default_reasons(
    session: Session,
    *,
    company_id: uuid.UUID,
) -> dict[str, int]:
    existing = {
        row.code: row
        for row in session.execute(
            select(ReasonORM).where(ReasonORM.company_id == company_id)
        )
        .scalars()
        .all()
    }
    created = 0
    updated = 0
    reactivated = 0
    reused = 0

    for item in DEFAULT_REASONS:
        row = existing.get(item.code)
        if row is None:
            session.add(
                ReasonORM(
                    company_id=company_id,
                    code=item.code,
                    name=item.name,
                    is_active=True,
                )
            )
            created += 1
            continue

        changed = False
        if row.name != item.name:
            row.name = item.name
            updated += 1
            changed = True
        if not row.is_active:
            row.is_active = True
            reactivated += 1
            changed = True
        if row.deleted_at is not None:
            row.deleted_at = None
            reactivated += 1
            changed = True
        if changed:
            session.add(row)
        else:
            reused += 1

    return {
        "created": created,
        "updated": updated,
        "reactivated": reactivated,
        "reused": reused,
        "total": len(DEFAULT_REASONS),
    }
