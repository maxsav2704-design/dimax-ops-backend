from __future__ import annotations

import uuid

from app.modules.doors.application.completion import enum_value
from app.modules.doors.application.sync_payload import build_door_sync_payload
from app.modules.doors.infrastructure.history_models import DoorStatusHistoryORM
from app.modules.sync.domain.enums import SyncChangeType


def record_door_transition(
    uow,
    *,
    company_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    door,
    from_status: object | None,
    source: str,
    reason: str | None = None,
) -> None:
    normalized_source = str(source or "SYSTEM").strip().upper()[:40] or "SYSTEM"
    uow.session.add(
        DoorStatusHistoryORM(
            company_id=company_id,
            door_id=door.id,
            changed_by_user_id=actor_user_id,
            from_status=enum_value(from_status) if from_status is not None else None,
            to_status=enum_value(door.status),
            reason=reason,
            source=normalized_source,
        )
    )
    uow.sync_change_log.add_change(
        company_id=company_id,
        change_type=SyncChangeType.DOOR,
        entity_id=door.id,
        project_id=door.project_id,
        installer_id=door.installer_id,
        payload=build_door_sync_payload(door),
    )
