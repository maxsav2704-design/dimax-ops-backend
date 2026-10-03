from __future__ import annotations

import uuid
from datetime import datetime

from app.modules.doors.application.completion import (
    create_completed_work_for_door,
    resolve_installation_time,
)
from app.modules.doors.application.transition_recorder import record_door_transition
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.domain.errors import DoorNotAssigned, InvalidTransition
from app.modules.earnings.application.factory_pricing import FactoryEarningsPricing
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
        happened_at: datetime | None = None,
        legacy_price_queue: bool = False,
        seen_price_list_id: uuid.UUID | None = None,
    ) -> dict:
        FactoryEarningsPricing.lock_company(uow, company_id)
        door = uow.doors.get(
            company_id=company_id, door_id=door_id,
            for_update=True, active_project_only=True,
        )
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
        if to_status == DoorStatus.INSTALLED:
            installed_at = resolve_installation_time(happened_at)

        door.status = to_status
        door.version = int(getattr(door, "version", 0) or 0) + 1
        if to_status == DoorStatus.INSTALLED:
            door.installed_at = installed_at
            door.is_locked = True
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
                legacy_price_queue=legacy_price_queue,
                seen_price_list_id=seen_price_list_id,
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
