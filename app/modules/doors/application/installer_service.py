from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.modules.doors.application.completion import (
    create_completed_work_for_door,
    resolve_installer_rate_snapshot,
)
from app.modules.doors.application.transition_recorder import record_door_transition
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.domain.errors import DoorNotAssigned, InvalidTransition
from app.modules.projects.application.status_service import ProjectStatusService
from app.shared.domain.errors import NotFound


ALLOWED_TRANSITIONS_INSTALLER: dict[DoorStatus, set[DoorStatus]] = {
    DoorStatus.NOT_INSTALLED: {DoorStatus.IN_PROGRESS},
    DoorStatus.IN_PROGRESS: {DoorStatus.INSTALLED},
}


class InstallerDoorService:
    @staticmethod
    def change_status(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        installer_id: uuid.UUID,
        door_id: uuid.UUID,
        to_status: DoorStatus,
        source: str = "MOBILE_API",
    ) -> dict:
        door = uow.doors.get(company_id=company_id, door_id=door_id)
        if not door:
            raise NotFound("Door not found", details={"door_id": str(door_id)})

        if getattr(door, "installer_id", None) != installer_id:
            raise DoorNotAssigned(
                "Door is not assigned to this installer",
                details={"door_id": str(door_id)},
            )

        from_status = getattr(door, "status", None)
        if getattr(door, "is_locked", False):
            raise InvalidTransition(
                "Door is locked. Admin override required.",
                field="status",
                meta={
                    "door_id": str(door_id),
                    "from_status": from_status.value if hasattr(from_status, "value") else str(from_status),
                    "to_status": to_status.value,
                },
            )

        allowed = ALLOWED_TRANSITIONS_INSTALLER.get(from_status, set())
        if to_status not in allowed:
            raise InvalidTransition(
                f"Door cannot move from {from_status.value if hasattr(from_status, 'value') else str(from_status)} to {to_status.value}",
                field="status",
                meta={
                    "door_id": str(door_id),
                    "from_status": from_status.value if hasattr(from_status, "value") else str(from_status),
                    "to_status": to_status.value,
                },
            )

        installed_at = None
        installer_rate_snapshot = None
        if to_status == DoorStatus.INSTALLED:
            installed_at = datetime.now(timezone.utc)
            current_snapshot = getattr(door, "installer_rate_snapshot", None)
            if current_snapshot is not None and Decimal(str(current_snapshot)) > 0:
                installer_rate_snapshot = Decimal(str(current_snapshot))
            else:
                installer_rate_snapshot = resolve_installer_rate_snapshot(
                    uow,
                    company_id=company_id,
                    installer_id=installer_id,
                    door_type_id=door.door_type_id,
                    at=installed_at,
                )

        door.status = to_status
        door.version = int(getattr(door, "version", 0) or 0) + 1
        if to_status == DoorStatus.INSTALLED:
            door.installed_at = installed_at
            door.is_locked = True
            door.installer_rate_snapshot = installer_rate_snapshot
        else:
            door.installed_at = None
            door.is_locked = False

        uow.doors.save(door)

        if to_status == DoorStatus.INSTALLED:
            create_completed_work_for_door(
                uow,
                company_id=company_id,
                installer_id=installer_id,
                door=door,
            )

        ProjectStatusService.recalc_and_set(
            uow=uow,
            company_id=company_id,
            project_id=door.project_id,
        )
        record_door_transition(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            door=door,
            from_status=from_status,
            source=source,
        )

        return {
            "id": door.id,
            "status": to_status.value,
            "version": door.version,
        }
