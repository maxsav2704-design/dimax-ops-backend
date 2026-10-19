"""Business actions the agent may propose.

Each action has a preview (fresh read, expected versions) and an execute step
that reuses the existing office command and verifies the saved state by reading
it back. Nothing here is reachable from the model loop without a stored
proposal and an explicit admin confirmation (see ProposalStore).
"""
from __future__ import annotations

from datetime import datetime, time, timezone

from app.modules.doors.domain.enums import DoorStatus
from app.modules.issues.application.admin_api_service import IssuesAdminApiService
from app.modules.issues.application.comments_service import IssueCommentsService
from app.modules.issues.application.installer_api_service import InstallerIssuesApiService
from app.modules.ai.infrastructure.read_tools import require_installer_id
from app.modules.doors.domain.errors import DoorNotAssigned
from app.modules.issues.domain.enums import IssueStatus
from app.modules.issues.infrastructure.models import IssueCommentORM
from app.shared.domain.errors import Conflict, NotFound, ValidationError


def _value(item):
    return item.value if hasattr(item, "value") else item


def _iso(value):
    return value.isoformat() if value else None


def _door(uow, company_id, door_id, *, for_update=False):
    door = uow.doors.get(company_id=company_id, door_id=door_id, for_update=for_update, active_project_only=True)
    if door is None:
        raise NotFound("Door not found", details={"door_id": str(door_id)})
    return door


def _issue(uow, company_id, issue_id, *, for_update=False):
    issue = uow.issues.get(company_id=company_id, issue_id=issue_id, for_update=for_update)
    if issue is None:
        raise NotFound("Issue not found", details={"issue_id": str(issue_id)})
    return issue


def _project_name(uow, company_id, project_id):
    project = uow.projects.get(company_id=company_id, project_id=project_id)
    return project.name if project else None


def issue_source(issue, door):
    return {"kind": "issue", "id": str(issue.id), "label": issue.title or door.unit_label, "path": f"/issues?issue_id={issue.id}"}


def door_source(door):
    return {"kind": "door", "id": str(door.id), "label": door.unit_label,
            "path": f"/projects?project_id={door.project_id}&focus_section=doors"}


class IssueReportAction:
    """Office report of an obstacle/defect on one position. Installation facts
    (installed / not installed, dates, prices, assignment) are never touched."""

    @staticmethod
    def preview(uow, user, args) -> dict:
        door = _door(uow, user.company_id, args.door_id)
        existing = uow.issues.get_by_door(company_id=user.company_id, door_id=door.id)
        mode = "new" if existing is None else ("reopen" if existing.status == IssueStatus.CLOSED else "append")
        door_after = (DoorStatus.ISSUE_OPEN.value
                      if not door.is_locked and door.status in {DoorStatus.NOT_INSTALLED, DoorStatus.IN_PROGRESS}
                      else _value(door.status))
        return {
            "entity": door_source(door),
            "summary": {"project": _project_name(uow, user.company_id, door.project_id), "door": door.unit_label,
                        "door_marking": door.door_code, "mode": mode},
            "before": {"door_status": _value(door.status), "issue_status": _value(existing.status) if existing else None,
                       "issue_title": existing.title if existing else None},
            "after": {"door_status": door_after, "issue_status": "OPEN", "title": args.title, "details": args.details,
                      "priority": args.priority or (_value(existing.priority) if mode == "append" else "P3"),
                      "workflow_state": _value(existing.workflow_state) if mode == "append" else "NEW"},
            "expected": {"door_version": int(door.version or 0), "issue_id": str(existing.id) if existing else None},
        }

    @staticmethod
    def execute(uow, user, args, expected) -> dict:
        door = _door(uow, user.company_id, args.door_id, for_update=True)
        existing = uow.issues.get_by_door(company_id=user.company_id, door_id=door.id)
        if int(door.version or 0) != expected.get("door_version") or (str(existing.id) if existing else None) != expected.get("issue_id"):
            raise Conflict("The position changed after the preview", details={"door_id": str(door.id)})
        dto = IssuesAdminApiService.report_issue(uow, company_id=user.company_id, actor_user_id=user.id, door_id=door.id,
                                                 title=args.title, details=args.details, priority=args.priority, source="ADMIN_AI")
        uow.session.flush()
        # Verify the saved state by reading it back, not by trusting the command result.
        issue = _issue(uow, user.company_id, dto.id)
        door = _door(uow, user.company_id, door.id)
        return {"result": {"issue_id": str(issue.id), "issue_status": _value(issue.status), "workflow_state": _value(issue.workflow_state),
                           "priority": _value(issue.priority), "door_status": _value(door.status), "door_version": int(door.version or 0)},
                "sources": [issue_source(issue, door), door_source(door)]}


class IssueCommentAction:
    @staticmethod
    def preview(uow, user, args) -> dict:
        issue = _issue(uow, user.company_id, args.issue_id)
        door = _door(uow, user.company_id, issue.door_id)
        return {
            "entity": issue_source(issue, door),
            "summary": {"project": _project_name(uow, user.company_id, door.project_id), "door": door.unit_label,
                        "issue_title": issue.title, "issue_status": _value(issue.status)},
            "before": {"issue_status": _value(issue.status), "workflow_state": _value(issue.workflow_state)},
            "after": {"comment": args.body},
            "expected": {"issue_status": _value(issue.status)},
        }

    @staticmethod
    def execute(uow, user, args, expected) -> dict:
        issue = _issue(uow, user.company_id, args.issue_id, for_update=True)
        if _value(issue.status) != expected.get("issue_status"):
            raise Conflict("The issue changed after the preview", details={"issue_id": str(issue.id)})
        door = _door(uow, user.company_id, issue.door_id)
        dto = IssueCommentsService.add_comment(uow, company_id=user.company_id, issue=issue, author_user_id=user.id,
                                               author_role="ADMIN", body=args.body)
        uow.session.flush()
        saved = uow.session.get(IssueCommentORM, dto.id)
        if saved is None:
            raise Conflict("The comment was not saved", details={"issue_id": str(issue.id)})
        return {"result": {"comment_id": str(saved.id), "issue_id": str(issue.id), "issue_status": _value(issue.status)},
                "sources": [issue_source(issue, door)]}


class IssueWorkflowAction:
    @staticmethod
    def _patch(args) -> dict:
        patch = {}
        if args.workflow_state:
            patch["workflow_state"] = args.workflow_state
        if args.priority:
            patch["priority"] = args.priority
        if args.due_date:
            try:
                day = datetime.strptime(args.due_date, "%Y-%m-%d").date()
            except ValueError:
                raise ValidationError("due_date must be a calendar date", field="due_date") from None
            patch["due_at"] = datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc)
        if not patch:
            raise ValidationError("Nothing to change: give a workflow state, a priority or a deadline")
        return patch

    @staticmethod
    def preview(uow, user, args) -> dict:
        patch = IssueWorkflowAction._patch(args)
        issue = _issue(uow, user.company_id, args.issue_id)
        door = _door(uow, user.company_id, issue.door_id)
        before = {"workflow_state": _value(issue.workflow_state), "priority": _value(issue.priority), "due_at": _iso(issue.due_at),
                  "issue_status": _value(issue.status)}
        after = dict(before)
        after.update({key: (_iso(value) if key == "due_at" else value) for key, value in patch.items()})
        if patch.get("workflow_state") == "CLOSED":
            after["issue_status"] = "CLOSED"
        elif "workflow_state" in patch and before["issue_status"] == "CLOSED":
            after["issue_status"] = "OPEN"
        return {
            "entity": issue_source(issue, door),
            "summary": {"project": _project_name(uow, user.company_id, door.project_id), "door": door.unit_label, "issue_title": issue.title},
            "before": before, "after": after,
            "expected": {"issue_updated_at": _iso(issue.updated_at)},
        }

    @staticmethod
    def execute(uow, user, args, expected) -> dict:
        patch = IssueWorkflowAction._patch(args)
        issue = _issue(uow, user.company_id, args.issue_id, for_update=True)
        if _iso(issue.updated_at) != expected.get("issue_updated_at"):
            raise Conflict("The issue changed after the preview", details={"issue_id": str(issue.id)})
        IssuesAdminApiService.update_issue_workflow(uow, company_id=user.company_id, actor_user_id=user.id,
                                                    issue_id=issue.id, patch=patch)
        uow.session.flush()
        issue = _issue(uow, user.company_id, issue.id)
        door = _door(uow, user.company_id, issue.door_id)
        return {"result": {"issue_id": str(issue.id), "issue_status": _value(issue.status), "workflow_state": _value(issue.workflow_state),
                           "priority": _value(issue.priority), "due_at": _iso(issue.due_at), "door_status": _value(door.status)},
                "sources": [issue_source(issue, door)]}


def installer_issue_source(issue, door):
    return {"kind": "issue", "id": str(issue.id), "label": issue.title or door.unit_label,
            "path": f"/installer/issues?project_id={door.project_id}&issue_id={issue.id}"}


def installer_door_source(door):
    return {"kind": "door", "id": str(door.id), "label": door.unit_label, "path": f"/installer/projects/{door.project_id}"}


class InstallerIssueReportAction:
    """The installer's own report of an obstacle/defect on an assigned position: the same
    command the app queues, with the assignment check inside. Nothing about completion."""

    @staticmethod
    def _my_door(uow, user, door_id, *, for_update=False):
        installer_id = require_installer_id(uow, user)
        door = uow.doors.get(company_id=user.company_id, door_id=door_id, for_update=for_update, active_project_only=True)
        if door is None or door.installer_id != installer_id:
            raise NotFound("Door not found", details={"door_id": str(door_id)})
        return door, installer_id

    @staticmethod
    def preview(uow, user, args) -> dict:
        door, _ = InstallerIssueReportAction._my_door(uow, user, args.door_id)
        existing = uow.issues.get_by_door(company_id=user.company_id, door_id=door.id)
        mode = "new" if existing is None else ("reopen" if existing.status == IssueStatus.CLOSED else "append")
        door_after = (DoorStatus.ISSUE_OPEN.value
                      if not door.is_locked and door.status in {DoorStatus.NOT_INSTALLED, DoorStatus.IN_PROGRESS}
                      else _value(door.status))
        return {
            "entity": installer_door_source(door),
            "summary": {"project": _project_name(uow, user.company_id, door.project_id), "door": door.unit_label,
                        "door_marking": door.door_code, "mode": mode},
            "before": {"door_status": _value(door.status), "issue_status": _value(existing.status) if existing else None,
                       "issue_title": existing.title if existing else None},
            "after": {"door_status": door_after, "issue_status": "OPEN", "title": args.title, "details": args.details,
                      "workflow_state": _value(existing.workflow_state) if mode == "append" else "NEW"},
            "expected": {"door_version": int(door.version or 0), "issue_id": str(existing.id) if existing else None},
        }

    @staticmethod
    def execute(uow, user, args, expected) -> dict:
        door, installer_id = InstallerIssueReportAction._my_door(uow, user, args.door_id, for_update=True)
        existing = uow.issues.get_by_door(company_id=user.company_id, door_id=door.id)
        if int(door.version or 0) != expected.get("door_version") or (str(existing.id) if existing else None) != expected.get("issue_id"):
            raise Conflict("The position changed after the preview", details={"door_id": str(door.id)})
        dto = InstallerIssuesApiService.create_issue(uow, company_id=user.company_id, installer_id=installer_id,
                                                     created_by_user_id=user.id, door_id=door.id, title=args.title,
                                                     details=args.details, source="INSTALLER_AI")
        uow.session.flush()
        issue = _issue(uow, user.company_id, dto.id)
        door = _door(uow, user.company_id, door.id)
        return {"result": {"issue_id": str(issue.id), "issue_status": _value(issue.status), "workflow_state": _value(issue.workflow_state),
                           "door_status": _value(door.status), "door_version": int(door.version or 0)},
                "sources": [installer_issue_source(issue, door), installer_door_source(door)]}


class InstallerIssueCommentAction:
    @staticmethod
    def _visible(uow, user, issue_id, *, for_update=False):
        installer_id = require_installer_id(uow, user)
        try:
            return InstallerIssuesApiService.ensure_issue_visible(uow, company_id=user.company_id, installer_id=installer_id,
                                                                  user_id=user.id, issue_id=issue_id, for_update=for_update)
        except DoorNotAssigned:
            raise NotFound("Issue not found", details={"issue_id": str(issue_id)}) from None

    @staticmethod
    def preview(uow, user, args) -> dict:
        issue, door = InstallerIssueCommentAction._visible(uow, user, args.issue_id)
        return {
            "entity": installer_issue_source(issue, door),
            "summary": {"project": _project_name(uow, user.company_id, door.project_id), "door": door.unit_label,
                        "issue_title": issue.title, "issue_status": _value(issue.status)},
            "before": {"issue_status": _value(issue.status), "workflow_state": _value(issue.workflow_state)},
            "after": {"comment": args.body},
            "expected": {"issue_status": _value(issue.status)},
        }

    @staticmethod
    def execute(uow, user, args, expected) -> dict:
        issue, door = InstallerIssueCommentAction._visible(uow, user, args.issue_id, for_update=True)
        if _value(issue.status) != expected.get("issue_status"):
            raise Conflict("The issue changed after the preview", details={"issue_id": str(issue.id)})
        dto = IssueCommentsService.add_comment(uow, company_id=user.company_id, issue=issue, author_user_id=user.id,
                                               author_role="INSTALLER", body=args.body)
        uow.session.flush()
        saved = uow.session.get(IssueCommentORM, dto.id)
        if saved is None:
            raise Conflict("The comment was not saved", details={"issue_id": str(issue.id)})
        return {"result": {"comment_id": str(saved.id), "issue_id": str(issue.id), "issue_status": _value(issue.status)},
                "sources": [installer_issue_source(issue, door)]}


ACTIONS = {
    "propose_issue_report": IssueReportAction,
    "propose_issue_comment": IssueCommentAction,
    "propose_issue_workflow": IssueWorkflowAction,
    "propose_my_issue_report": InstallerIssueReportAction,
    "propose_my_issue_comment": InstallerIssueCommentAction,
}
