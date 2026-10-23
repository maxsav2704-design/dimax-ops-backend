from __future__ import annotations

from datetime import datetime, timezone

from app.shared.domain.errors import Conflict, ForbiddenScope, NotFound, ValidationError
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.application.completion import (
    create_completed_work_for_door,
    reverse_completed_work_for_door,
    resolve_installation_time,
)
from app.modules.doors.application.commands import (
    AdminOverrideDoor,
    MarkDoorInstalled,
    MarkDoorNotInstalled,
)
from app.modules.doors.application.stages_service import ensure_not_stage_door
from app.modules.doors.application.transition_recorder import record_door_transition
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.domain.errors import DoorNotAssigned
from app.modules.earnings.application.factory_pricing import FactoryEarningsPricing
from app.modules.issues.domain.enums import IssueStatus, IssueWorkflowState
from app.modules.issues.application.sync_payload import publish_issue_change
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.application.status_service import ProjectStatusService


def utcnow():
    return datetime.now(timezone.utc)


def _ensure_reason_exists(uow, *, company_id, reason_id) -> None:
    reason = uow.reasons.get(company_id=company_id, reason_id=reason_id)
    if reason is None:
        raise ValidationError("reason_id not found")
    if not reason.is_active:
        raise ValidationError("reason is inactive")


def _bump_door_version(door) -> None:
    door.version = int(getattr(door, "version", 0) or 0) + 1


def _door_action_result(door) -> dict:
    return {
        "id": door.id,
        "status": door.status.value if hasattr(door.status, "value") else str(door.status),
        "version": int(getattr(door, "version", 0) or 0),
    }


class DoorUseCases:
    @staticmethod
    def mark_installed(uow, cmd: MarkDoorInstalled) -> dict:
        FactoryEarningsPricing.lock_company(uow, cmd.company_id)
        door = uow.doors.get(
            company_id=cmd.company_id, door_id=cmd.door_id, for_update=True,
            active_project_only=cmd.expected_installer_id is not None,
        )
        if not door:
            raise NotFound("Door not found", details={"door_id": str(cmd.door_id)})
        if (
            cmd.expected_installer_id is not None
            and door.installer_id != cmd.expected_installer_id
        ):
            raise DoorNotAssigned(
                "Door is not assigned to this installer",
                details={"door_id": str(cmd.door_id)},
            )
        from_status = door.status

        # lock-инвариант
        if door.is_locked:
            raise Conflict(
                "Door is locked (already installed). Admin override required.",
                details={"door_id": str(cmd.door_id)},
            )

        ensure_not_stage_door(uow, door)

        # ставим installed
        installed_at = resolve_installation_time(cmd.happened_at, received_at=utcnow())

        door.status = DoorStatus.INSTALLED
        door.installed_at = installed_at
        door.is_locked = True
        door.reason_id = None
        door.comment = None
        _bump_door_version(door)

        uow.doors.save(door)
        create_completed_work_for_door(
            uow,
            company_id=cmd.company_id,
            installer_id=door.installer_id,
            door=door,
            legacy_price_queue=cmd.legacy_price_queue,
            seen_price_list_id=cmd.seen_price_list_id,
            approved_work_price=cmd.approved_work_price,
        )

        # закрываем issue если было
        issue = uow.issues.get_by_door(
            company_id=cmd.company_id, door_id=cmd.door_id
        )
        if issue and issue.status != IssueStatus.CLOSED:
            issue.status = IssueStatus.CLOSED
            issue.workflow_state = IssueWorkflowState.CLOSED
            uow.issues.save(issue)
            publish_issue_change(uow, issue=issue, door=door)

        ProjectStatusService.recalc_and_set(
            uow=uow,
            company_id=cmd.company_id,
            project_id=door.project_id,
        )

        record_door_transition(
            uow,
            company_id=cmd.company_id,
            actor_user_id=cmd.actor_user_id,
            door=door,
            from_status=from_status,
            source=getattr(cmd, "source", "ADMIN_OVERRIDE"),
            reason=getattr(cmd, "override_reason", None)
            or getattr(cmd, "comment", None),
        )
        return _door_action_result(door)

    @staticmethod
    def mark_not_installed(uow, cmd: MarkDoorNotInstalled) -> dict:
        FactoryEarningsPricing.lock_company(uow, cmd.company_id)
        door = uow.doors.get(
            company_id=cmd.company_id, door_id=cmd.door_id, for_update=True,
            active_project_only=cmd.expected_installer_id is not None,
        )
        if not door:
            raise NotFound("Door not found", details={"door_id": str(cmd.door_id)})
        if (
            cmd.expected_installer_id is not None
            and door.installer_id != cmd.expected_installer_id
        ):
            raise DoorNotAssigned(
                "Door is not assigned to this installer",
                details={"door_id": str(cmd.door_id)},
            )
        from_status = door.status

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
        _bump_door_version(door)

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
        issue.workflow_state = IssueWorkflowState.NEW
        publish_issue_change(uow, issue=issue, door=door)

        ProjectStatusService.recalc_and_set(
            uow=uow,
            company_id=cmd.company_id,
            project_id=door.project_id,
        )

        record_door_transition(
            uow,
            company_id=cmd.company_id,
            actor_user_id=cmd.actor_user_id,
            door=door,
            from_status=from_status,
            source=getattr(cmd, "source", "ADMIN_OVERRIDE"),
            reason=getattr(cmd, "override_reason", None)
            or getattr(cmd, "comment", None),
        )
        return _door_action_result(door)

    @staticmethod
    def admin_override(uow, cmd: AdminOverrideDoor, *, actor_role: str) -> None:
        if actor_role != "ADMIN":
            raise ForbiddenScope("Admin only")

        FactoryEarningsPricing.lock_company(uow, cmd.company_id)
        door = uow.doors.get(company_id=cmd.company_id, door_id=cmd.door_id, for_update=True)
        if not door:
            raise NotFound("Door not found", details={"door_id": str(cmd.door_id)})
        from_status = door.status

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
            ensure_not_stage_door(uow, door)
            installed_at = (
                door.installed_at
                if from_status == DoorStatus.INSTALLED and door.installed_at is not None
                else utcnow()
            )

            door.status = DoorStatus.INSTALLED
            door.installed_at = installed_at
            door.is_locked = True
            door.reason_id = None
            door.comment = None
            create_completed_work_for_door(
                uow,
                company_id=cmd.company_id,
                installer_id=door.installer_id,
                door=door,
            )

            issue = uow.issues.get_by_door(
                company_id=cmd.company_id, door_id=cmd.door_id
            )
            if issue:
                issue.status = IssueStatus.CLOSED
                issue.workflow_state = IssueWorkflowState.CLOSED
                uow.issues.save(issue)
                publish_issue_change(uow, issue=issue, door=door)

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

            reverse_completed_work_for_door(
                uow,
                company_id=cmd.company_id,
                door=door,
                reason=cmd.override_reason
                or "Admin override: door marked NOT_INSTALLED",
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
            issue.workflow_state = IssueWorkflowState.NEW
            publish_issue_change(uow, issue=issue, door=door)

        else:
            raise ValidationError(
                "new_status must be INSTALLED or NOT_INSTALLED"
            )

        _bump_door_version(door)
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

        record_door_transition(
            uow,
            company_id=cmd.company_id,
            actor_user_id=cmd.actor_user_id,
            door=door,
            from_status=from_status,
            source=getattr(cmd, "source", "ADMIN_OVERRIDE"),
            reason=getattr(cmd, "override_reason", None)
            or getattr(cmd, "comment", None),
        )
