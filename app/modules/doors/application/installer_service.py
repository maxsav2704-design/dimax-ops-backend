from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.domain.errors import DoorNotAssigned, InvalidTransition
from app.modules.doors.infrastructure.history_models import DoorStatusHistoryORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
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

        door.status = to_status
        door.version = int(getattr(door, "version", 0) or 0) + 1
        if to_status == DoorStatus.INSTALLED:
            door.installed_at = datetime.now(timezone.utc)
            door.is_locked = True
        else:
            door.installed_at = None
            door.is_locked = False

        uow.doors.save(door)
        uow.session.add(
            DoorStatusHistoryORM(
                company_id=company_id,
                door_id=door.id,
                changed_by_user_id=actor_user_id,
                from_status=from_status.value if hasattr(from_status, "value") else str(from_status),
                to_status=to_status.value,
                source="MOBILE",
            )
        )

        if to_status == DoorStatus.INSTALLED:
            InstallerDoorService._create_completed_work(
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

        return {
            "id": door.id,
            "status": to_status.value,
            "version": door.version,
        }

    @staticmethod
    def _create_completed_work(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        door,
    ) -> None:
        rate_snapshot = Decimal(str(getattr(door, "installer_rate_snapshot", None) or "0"))
        amount_snapshot = rate_snapshot
        completed_at = getattr(door, "installed_at", None) or datetime.now(timezone.utc)
        uow.session.add(
            CompletedWorkORM(
                company_id=company_id,
                project_id=door.project_id,
                door_id=door.id,
                installer_id=installer_id,
                completed_at=completed_at,
                quantity=Decimal("1.00"),
                rate_snapshot=rate_snapshot,
                amount_snapshot=amount_snapshot,
                entry_type="ORIGINAL",
                correction_ref_id=None,
                reason=None,
            )
        )
