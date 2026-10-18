from __future__ import annotations

import json

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from app.api.v1.deps import CurrentUser
from app.modules.ai.api.schemas import AiSource
from app.modules.ai.domain.tools import TOOL_SPECS, allowed_tool_names, ensure_ai_admin
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.reasons.infrastructure.models import ReasonORM
from app.modules.issues.application.comments_service import IssueCommentsService
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM, UserORM
from app.shared.domain.errors import ForbiddenScope, NotFound, ValidationError


def value(item):
    return item.value if hasattr(item, "value") else item


def load_actor(uow, original: CurrentUser) -> CurrentUser:
    row = uow.session.execute(
        select(UserORM.role, AdminProfileORM.admin_scope).select_from(UserORM)
        .join(CompanyORM, CompanyORM.id == UserORM.company_id)
        .join(AdminProfileORM, (AdminProfileORM.user_id == UserORM.id) &
              (AdminProfileORM.company_id == UserORM.company_id))
        .where(UserORM.id == original.id, UserORM.company_id == original.company_id,
               UserORM.is_active.is_(True), CompanyORM.is_active.is_(True))
    ).first()
    if row is None:
        raise ForbiddenScope("AI access is no longer available")
    return ensure_ai_admin(CurrentUser(id=original.id, company_id=original.company_id,
                                      role=value(row.role), admin_scope=row.admin_scope))


class ReadTools:
    """Read tools return data. Action tools never execute: with a ProposalStore
    bound to the running task they store a proposal for the user's decision."""

    def __init__(self, user: CurrentUser, uow_factory, *, proposals=None, task_id=None, conversation_id=None):
        self.user = user
        self.uow_factory = uow_factory
        self.sources: dict[tuple[str, str], AiSource] = {}
        self.proposals = proposals
        self.task_id = task_id
        self.conversation_id = conversation_id
        self.proposal_ids: list[str] = []

    def check_access(self) -> CurrentUser:
        with self.uow_factory() as uow:
            current = load_actor(uow, self.user)
            # A permission change invalidates this entire run, including earlier data.
            if current.admin_scope != self.user.admin_scope:
                raise ForbiddenScope("AI permissions changed; start a new request")
            return current

    def _source(self, kind, row_id, label, path):
        source = AiSource(kind=kind, id=row_id, label=label, path=path)
        # Bound UI references even when the model requests several pages.
        if len(self.sources) < 100:
            self.sources[(kind, str(row_id))] = source
        return source.model_dump(mode="json")

    def _project(self, uow, project_id):
        project = uow.projects.get(company_id=self.user.company_id, project_id=project_id)
        if project is None:
            raise NotFound("Project not found")
        return project

    def call(self, name: str, arguments: str) -> dict:
        if name not in TOOL_SPECS or name not in allowed_tool_names(self.user):
            raise ForbiddenScope("Tool is not available")
        if not isinstance(arguments, str) or len(arguments) > 2000:
            raise ValidationError("Invalid tool arguments")
        try:
            args = TOOL_SPECS[name].args.model_validate_json(arguments)
        except PydanticValidationError:
            raise ValidationError("Invalid tool arguments") from None
        if TOOL_SPECS[name].kind == "action":
            if self.proposals is None or self.task_id is None:
                raise ForbiddenScope("Business actions are not available in this run")
            result = self.proposals.propose(task_id=self.task_id, conversation_id=self.conversation_id, name=name, args=args)
            self.proposal_ids.append(result["proposal_id"])
            return result
        with self.uow_factory() as uow:
            current = load_actor(uow, self.user)
            if current.admin_scope != self.user.admin_scope or name not in allowed_tool_names(current):
                raise ForbiddenScope("AI permissions changed; start a new request")
            handler = getattr(self, f"_{name}")
            result = handler(uow, args)
        # Reject accidental oversized tool output before sending it externally.
        if len(json.dumps(result, ensure_ascii=False)) > 45000:
            raise ValidationError("Tool result exceeds the page limit")
        return result

    def _search_projects(self, uow, args):
        rows = uow.projects.list(company_id=self.user.company_id, q=args.q,
                                 limit=args.limit + 1, offset=args.offset)
        items = [{"id": str(p.id), "name": p.name, "code": p.code,
                  "address": p.address, "lifecycle_status": p.lifecycle_status,
                  "source": self._source("project", p.id, p.name, f"/projects?project_id={p.id}")}
                 for p in rows[:args.limit]]
        return {"items": items, "has_more": len(rows) > args.limit, "offset": args.offset}

    def _project_summary(self, uow, args):
        p = self._project(uow, args.project_id)
        counts = uow.session.execute(select(DoorORM.status, func.count(DoorORM.id))
                    .where(DoorORM.company_id == self.user.company_id, DoorORM.project_id == p.id)
                    .group_by(DoorORM.status)).all()
        issues = uow.session.execute(select(func.count(IssueORM.id)).join(DoorORM, DoorORM.id == IssueORM.door_id)
                    .where(IssueORM.company_id == self.user.company_id, DoorORM.company_id == self.user.company_id,
                           DoorORM.project_id == p.id, IssueORM.status == "OPEN")).scalar_one()
        return {"id": str(p.id), "name": p.name, "lifecycle_status": p.lifecycle_status,
                "health_status": p.health_status,
                "planned_end_date": p.planned_end_date.isoformat() if p.planned_end_date else None,
                "door_status_counts": {value(status): count for status, count in counts},
                "total_doors": sum(count for _, count in counts), "open_issues": issues,
                "source": self._source("project", p.id, p.name, f"/projects?project_id={p.id}")}

    def _list_project_doors(self, uow, args):
        p = self._project(uow, args.project_id)
        stmt = select(DoorORM, ReasonORM.name, DoorTypeORM.name).outerjoin(
            ReasonORM, (ReasonORM.id == DoorORM.reason_id) & (ReasonORM.company_id == self.user.company_id)
        ).outerjoin(DoorTypeORM, (DoorTypeORM.id == DoorORM.door_type_id) &
                    (DoorTypeORM.company_id == self.user.company_id)).where(
            DoorORM.company_id == self.user.company_id, DoorORM.project_id == p.id)
        if args.status:
            stmt = stmt.where(DoorORM.status == args.status)
        rows = uow.session.execute(stmt.order_by(DoorORM.unit_label, DoorORM.id)
                    .limit(args.limit + 1).offset(args.offset)).all()
        items = [{"id": str(d.id), "unit_label": d.unit_label, "door_code": d.door_code,
                  "house_number": d.house_number, "floor_label": d.floor_label,
                  "apartment_number": d.apartment_number, "status": value(d.status),
                  "installer_id": str(d.installer_id) if d.installer_id else None,
                  "reason_id": str(d.reason_id) if d.reason_id else None,
                  "reason_name": reason_name, "door_type_name": door_type_name,
                  "comment": d.comment, "version": d.version,
                  "installed_at": d.installed_at.isoformat() if d.installed_at else None,
                  "source": self._source("door", d.id, d.unit_label, f"/projects?project_id={p.id}&focus_section=doors")}
                 for d, reason_name, door_type_name in rows[:args.limit]]
        return {"items": items, "has_more": len(rows) > args.limit, "offset": args.offset}

    def _list_project_issues(self, uow, args):
        p = self._project(uow, args.project_id)
        stmt = select(IssueORM, DoorORM.unit_label).join(DoorORM, DoorORM.id == IssueORM.door_id).where(
            IssueORM.company_id == self.user.company_id, DoorORM.company_id == self.user.company_id,
            DoorORM.project_id == p.id)
        if args.status:
            stmt = stmt.where(IssueORM.status == args.status)
        rows = uow.session.execute(stmt.order_by(IssueORM.created_at, IssueORM.id)
                    .limit(args.limit + 1).offset(args.offset)).all()
        items = [{"id": str(i.id), "door_id": str(i.door_id), "unit_label": label,
                  "title": i.title, "details": i.details, "status": value(i.status),
                  "workflow_state": value(i.workflow_state), "priority": value(i.priority),
                  "due_at": i.due_at.isoformat() if i.due_at else None,
                  "source": self._source("issue", i.id, i.title or label, f"/issues?issue_id={i.id}")}
                 for i, label in rows[:args.limit]]
        return {"items": items, "has_more": len(rows) > args.limit, "offset": args.offset}

    def _search_installers(self, uow, args):
        rows = uow.installers.list(company_id=self.user.company_id, q=args.q, is_active=None,
                                   limit=args.limit + 1, offset=args.offset)
        return {"items": [{"id": str(i.id), "full_name": i.full_name,
                           "status": i.status, "is_active": i.is_active,
                           "source": self._source("installer", i.id, i.full_name, f"/installers?installer_id={i.id}")}
                          for i in rows[:args.limit]],
                "has_more": len(rows) > args.limit, "offset": args.offset}

    def _get_door(self, uow, args):
        row = uow.session.execute(select(DoorORM, ReasonORM.name, DoorTypeORM.name).outerjoin(
            ReasonORM, (ReasonORM.id == DoorORM.reason_id) & (ReasonORM.company_id == self.user.company_id)
        ).outerjoin(DoorTypeORM, (DoorTypeORM.id == DoorORM.door_type_id) & (DoorTypeORM.company_id == self.user.company_id)
        ).where(DoorORM.company_id == self.user.company_id, DoorORM.id == args.door_id)).first()
        if row is None:
            raise NotFound("Door not found")
        d, reason_name, door_type_name = row
        p = self._project(uow, d.project_id)
        issue = uow.issues.get_by_door(company_id=self.user.company_id, door_id=d.id)
        return {"id": str(d.id), "door_id": str(d.id), "project_id": str(p.id), "project_name": p.name,
                "unit_label": d.unit_label, "door_code": d.door_code, "house_number": d.house_number,
                "floor_label": d.floor_label, "apartment_number": d.apartment_number,
                "status": value(d.status), "version": d.version, "is_locked": d.is_locked,
                "installer_id": str(d.installer_id) if d.installer_id else None,
                "reason_name": reason_name, "door_type_name": door_type_name,
                "installed_at": d.installed_at.isoformat() if d.installed_at else None,
                "comment": {"untrusted_text": d.comment},
                "issue": {"id": str(issue.id), "status": value(issue.status), "workflow_state": value(issue.workflow_state),
                          "title": {"untrusted_text": issue.title}} if issue else None,
                "source": self._source("door", d.id, d.unit_label, f"/projects?project_id={p.id}&focus_section=doors")}

    def _get_issue(self, uow, args):
        row = uow.session.execute(select(IssueORM, DoorORM).join(DoorORM, DoorORM.id == IssueORM.door_id).where(
            IssueORM.company_id == self.user.company_id, DoorORM.company_id == self.user.company_id,
            IssueORM.id == args.issue_id)).first()
        if row is None:
            raise NotFound("Issue not found")
        i, d = row
        p = self._project(uow, d.project_id)
        comments = IssueCommentsService.list_comments(uow, company_id=self.user.company_id, issue_id=i.id)
        return {"id": str(i.id), "issue_id": str(i.id), "door_id": str(d.id), "unit_label": d.unit_label,
                "project_id": str(p.id), "project_name": p.name, "door_status": value(d.status),
                "status": value(i.status), "workflow_state": value(i.workflow_state), "priority": value(i.priority),
                "due_at": i.due_at.isoformat() if i.due_at else None,
                "owner_user_id": str(i.owner_user_id) if i.owner_user_id else None,
                "updated_at": i.updated_at.isoformat() if i.updated_at else None,
                "title": {"untrusted_text": i.title}, "details": {"untrusted_text": i.details},
                "comments": [{"author": c.author_name, "created_at": c.created_at.isoformat() if c.created_at else None,
                              "body": {"untrusted_text": c.body}} for c in comments[-20:]],
                "source": self._source("issue", i.id, i.title or d.unit_label, f"/issues?issue_id={i.id}")}
