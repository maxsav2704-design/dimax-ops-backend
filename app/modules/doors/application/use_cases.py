from __future__ import annotations

from datetime import datetime, timezone

from app.shared.domain.errors import Conflict, Forbidden, NotFound, ValidationError
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.application.commands import (
    AdminOverrideDoor,
    MarkDoorInstalled,
    MarkDoorNotInstalled,
)
from app.modules.doors.domain.enums import DoorStatus
from app.modules.issues.domain.enums import IssueStatus
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.application.status_service import ProjectStatusService
from app.modules.sync.domain.enums import SyncChangeType


def utcnow():
    return datetime.now(timezone.utc)


def _ensure_reason_exists(uow, *, company_id, reason_id) -> None:
    reason = uow.reasons.get(company_id=company_id, reason_id=reason_id)
    if reason is None:
        raise ValidationError("reason_id not found")
    if not reason.is_active:
        raise ValidationError("reason is inactive")


def _resolve_installer_rate_snapshot(
    uow,
    *,
    company_id,
    installer_id,
    door_type_id,
    at=None,
):
    if installer_id is None:
        return None
    rate = uow.installer_rates.get_by_keys(
        company_id=company_id,
        installer_id=installer_id,
        door_type_id=door_type_id,
        at=at,
    )
    if rate is None:
        return None
    return rate.price


class DoorUseCases:
    @staticmethod
    def mark_installed(uow, cmd: MarkDoorInstalled) -> None:
        door = uow.doors.get(company_id=cmd.company_id, door_id=cmd.door_id)
        if not door:
            raise NotFound("Door not found", details={"door_id": str(cmd.door_id)})

        # lock-инвариант
        if door.is_locked:
            raise Conflict(
                "Door is locked (already installed). Admin override required.",
                details={"door_id": str(cmd.door_id)},
            )

        # ставим installed
        door.status = DoorStatus.INSTALLED
        door.installed_at = utcnow()
        door.is_locked = True
        door.reason_id = None
        door.comment = None
        door.installer_rate_snapshot = _resolve_installer_rate_snapshot(
            uow,
            company_id=cmd.company_id,
            installer_id=door.installer_id,
            door_type_id=door.door_type_id,
            at=door.installed_at,
        )

        uow.doors.save(door)

        # закрываем issue если было
        issue = uow.issues.get_by_door(
            company_id=cmd.company_id, door_id=cmd.door_id
        )
        if issue and issue.status != IssueStatus.CLOSED:
            issue.status = IssueStatus.CLOSED
            uow.issues.save(issue)

        ProjectStatusService.recalc_and_set(
            uow=uow,
            company_id=cmd.company_id,
            project_id=door.project_id,
        )

        uow.sync_change_log.add_change(
            company_id=cmd.company_id,
            change_type=SyncChangeType.DOOR,
            entity_id=door.id,
            project_id=door.project_id,
            installer_id=door.installer_id,
            payload={
                "id": str(door.id),
                "project_id": str(door.project_id),
                "door_type_id": str(door.door_type_id),
                "unit_label": door.unit_label,
                "order_number": door.order_number,
                "house_number": door.house_number,
                "floor_label": door.floor_label,
                "apartment_number": door.apartment_number,
                "location_code": door.location_code,
                "door_marking": door.door_marking,
                "status": str(door.status),
                "comment": door.comment,
                "updated_at": utcnow().isoformat(),
            },
        )

    @staticmethod
    def mark_not_installed(uow, cmd: MarkDoorNotInstalled) -> None:
        door = uow.doors.get(company_id=cmd.company_id, door_id=cmd.door_id)
        if not door:
            raise NotFound("Door not found", details={"door_id": str(cmd.door_id)})

        if door.is_locked:
            raise Conflict(
                "Door is locked (already installed). Admin override required.",
                details={"door_id": str(cmd.door_id)},
            )

        if not cmd.reason_id:
            raise ValidationError("reason_id is required for NOT_INSTALLED")
        _ensure_reason_exists(
            uow,
            company_id=cmd.company_id,
            reason_id=cmd.reason_id,
        )

        door.status = DoorStatus.NOT_INSTALLED
        door.reason_id = cmd.reason_id
        door.comment = cmd.comment
        door.installed_at = None
        door.installer_rate_snapshot = None

        uow.doors.save(door)

        # issue: создать если нет, иначе открыть
        issue = uow.issues.get_by_door(
            company_id=cmd.company_id, door_id=cmd.door_id
        )
        if not issue:
            issue = IssueORM(
                company_id=cmd.company_id,
                door_id=cmd.door_id,
                status=IssueStatus.OPEN,
                title="Door not installed",
                details=cmd.comment,
            )
        else:
            issue.status = IssueStatus.OPEN
            issue.details = cmd.comment

        uow.issues.save(issue)

        ProjectStatusService.recalc_and_set(
            uow=uow,
            company_id=cmd.company_id,
            project_id=door.project_id,
        )

        uow.sync_change_log.add_change(
            company_id=cmd.company_id,
            change_type=SyncChangeType.DOOR,
            entity_id=door.id,
            project_id=door.project_id,
            installer_id=door.installer_id,
            payload={
                "id": str(door.id),
                "project_id": str(door.project_id),
                "door_type_id": str(door.door_type_id),
                "unit_label": door.unit_label,
                "order_number": door.order_number,
                "house_number": door.house_number,
                "floor_label": door.floor_label,
                "apartment_number": door.apartment_number,
                "location_code": door.location_code,
                "door_marking": door.door_marking,
                "status": str(door.status),
                "comment": door.comment,
                "updated_at": utcnow().isoformat(),
            },
        )

    @staticmethod
    def admin_override(uow, cmd: AdminOverrideDoor, *, actor_role: str) -> None:
        if actor_role != "ADMIN":
            raise Forbidden("Admin only")

        door = uow.doors.get(company_id=cmd.company_id, door_id=cmd.door_id)
        if not door:
            raise NotFound("Door not found", details={"door_id": str(cmd.door_id)})

        before = {
            "status": door.status.value,
            "reason_id": str(door.reason_id) if door.reason_id else None,
            "comment": door.comment,
            "installed_at": (
                door.installed_at.isoformat() if door.installed_at else None
            ),
            "is_locked": door.is_locked,
            "installer_rate_snapshot": (
                str(door.installer_rate_snapshot)
                if door.installer_rate_snapshot is not None
                else None
            ),
        }

        if cmd.new_status == "INSTALLED":
            door.status = DoorStatus.INSTALLED
            door.installed_at = utcnow()
            door.is_locked = True
            door.reason_id = None
            door.comment = None
            door.installer_rate_snapshot = _resolve_installer_rate_snapshot(
                uow,
                company_id=cmd.company_id,
                installer_id=door.installer_id,
                door_type_id=door.door_type_id,
                at=door.installed_at,
            )

            issue = uow.issues.get_by_door(
                company_id=cmd.company_id, door_id=cmd.door_id
            )
            if issue:
                issue.status = IssueStatus.CLOSED
                uow.issues.save(issue)

        elif cmd.new_status == "NOT_INSTALLED":
            if not cmd.reason_id:
                raise ValidationError(
                    "reason_id is required for NOT_INSTALLED"
                )
            _ensure_reason_exists(
                uow,
                company_id=cmd.company_id,
                reason_id=cmd.reason_id,
            )

            door.status = DoorStatus.NOT_INSTALLED
            door.reason_id = cmd.reason_id
            door.comment = cmd.comment
            door.installed_at = None
            door.is_locked = False
            door.installer_rate_snapshot = None

            issue = uow.issues.get_by_door(
                company_id=cmd.company_id, door_id=cmd.door_id
            )
            if not issue:
                issue = IssueORM(
                    company_id=cmd.company_id,
                    door_id=cmd.door_id,
                    status=IssueStatus.OPEN,
                    title="Door not installed (override)",
                    details=cmd.comment,
                )
            else:
                issue.status = IssueStatus.OPEN
                issue.details = cmd.comment
            uow.issues.save(issue)

        else:
            raise ValidationError(
                "new_status must be INSTALLED or NOT_INSTALLED"
            )

        uow.doors.save(door)

        after = {
            "status": door.status.value,
            "reason_id": str(door.reason_id) if door.reason_id else None,
            "comment": door.comment,
            "installed_at": (
                door.installed_at.isoformat() if door.installed_at else None
            ),
            "is_locked": door.is_locked,
            "installer_rate_snapshot": (
                str(door.installer_rate_snapshot)
                if door.installer_rate_snapshot is not None
                else None
            ),
        }

        uow.audit.add(
            AuditLogORM(
                company_id=cmd.company_id,
                actor_user_id=cmd.actor_user_id,
                entity_type="Door",
                entity_id=door.id,
                action="ADMIN_OVERRIDE",
                reason=cmd.override_reason,
                before=before,
                after=after,
            )
        )

        ProjectStatusService.recalc_and_set(
            uow=uow,
            company_id=cmd.company_id,
            project_id=door.project_id,
        )

        uow.sync_change_log.add_change(
            company_id=cmd.company_id,
            change_type=SyncChangeType.DOOR,
            entity_id=door.id,
            project_id=door.project_id,
            installer_id=door.installer_id,
            payload={
                "id": str(door.id),
                "project_id": str(door.project_id),
                "door_type_id": str(door.door_type_id),
                "unit_label": door.unit_label,
                "order_number": door.order_number,
                "house_number": door.house_number,
                "floor_label": door.floor_label,
                "apartment_number": door.apartment_number,
                "location_code": door.location_code,
                "door_marking": door.door_marking,
                "status": str(door.status),
                "comment": door.comment,
                "updated_at": utcnow().isoformat(),
            },
        )
