from __future__ import annotations

import json

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from app.api.v1.deps import CurrentUser
from app.modules.ai.api.schemas import AiSource
from app.modules.ai.domain.tools import TOOL_SPECS, allowed_tool_names, ensure_ai_admin
from app.modules.doors.domain.errors import DoorNotAssigned
from app.modules.issues.application.installer_api_service import InstallerIssuesApiService
from datetime import datetime, timedelta, timezone

from app.modules.calendar.infrastructure.models import CalendarEventAssigneeORM
from app.modules.calendar.infrastructure.repositories import CalendarRepository
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.journal.infrastructure.models import JournalORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.reasons.infrastructure.models import ReasonORM
from app.modules.issues.application.comments_service import IssueCommentsService
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM, UserORM
from app.shared.domain.errors import ForbiddenScope, NotFound, ValidationError


def value(item):
    return item.value if hasattr(item, "value") else item


def load_actor(uow, original: CurrentUser) -> CurrentUser:
    """The live actor: role from users, scope from the admin profile (None for installers)."""
    row = uow.session.execute(
        select(UserORM.role, AdminProfileORM.admin_scope).select_from(UserORM)
        .join(CompanyORM, CompanyORM.id == UserORM.company_id)
        .outerjoin(AdminProfileORM, (AdminProfileORM.user_id == UserORM.id) &
                   (AdminProfileORM.company_id == UserORM.company_id))
        .where(UserORM.id == original.id, UserORM.company_id == original.company_id,
               UserORM.is_active.is_(True), CompanyORM.is_active.is_(True))
    ).first()
    if row is None:
        raise ForbiddenScope("AI access is no longer available")
    role = value(row.role)
    if role == "INSTALLER":
        if installer_id_for(uow, original) is None:
            raise ForbiddenScope("Installer profile not linked to user")
        return CurrentUser(id=original.id, company_id=original.company_id, role="INSTALLER", admin_scope=None)
    return ensure_ai_admin(CurrentUser(id=original.id, company_id=original.company_id,
                                      role=role, admin_scope=row.admin_scope))


def installer_id_for(uow, user: CurrentUser):
    """The installer record of this user (active, not deleted), or None."""
    installer = uow.installers.get_by_user_id(company_id=user.company_id, user_id=user.id)
    return installer.id if installer is not None else None


def require_installer_id(uow, user: CurrentUser):
    installer_id = installer_id_for(uow, user)
    if installer_id is None:
        raise ForbiddenScope("Installer profile not linked to user")
    return installer_id


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
            if current.admin_scope != self.user.admin_scope or current.role != self.user.role:
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
            if current.admin_scope != self.user.admin_scope or current.role != self.user.role or name not in allowed_tool_names(current):
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

    # ---- installer tools: the installer's own positions only ------------------------------------

    def _my_project(self, uow, project_id, installer_id):
        p = uow.projects.get(company_id=self.user.company_id, project_id=project_id)
        if p is None or not uow.doors.has_any_for_installer(company_id=self.user.company_id, project_id=p.id, installer_id=installer_id):
            raise NotFound("Project not found")
        return p

    def _my_projects(self, uow, args):
        installer_id = require_installer_id(uow, self.user)
        ids = uow.doors.list_project_ids_for_installer(company_id=self.user.company_id, installer_id=installer_id)
        rows = sorted(uow.projects.list_by_ids(company_id=self.user.company_id, ids=ids), key=lambda p: (p.name or "", str(p.id)))
        page = rows[args.offset:args.offset + args.limit + 1]
        items = [{"id": str(p.id), "name": p.name, "address": p.address, "lifecycle_status": value(p.lifecycle_status),
                  "health_status": value(p.health_status),
                  "source": self._source("project", p.id, p.name, f"/installer/projects/{p.id}")} for p in page[:args.limit]]
        return {"items": items, "has_more": len(page) > args.limit, "offset": args.offset}

    def _my_project_summary(self, uow, args):
        installer_id = require_installer_id(uow, self.user)
        p = self._my_project(uow, args.project_id, installer_id)
        doors = uow.doors.list_by_project_for_installer(company_id=self.user.company_id, project_id=p.id, installer_id=installer_id)
        counts: dict[str, int] = {}
        for d in doors:
            counts[value(d.status)] = counts.get(value(d.status), 0) + 1
        issues = len(uow.issues.list_open_by_project_for_installer(company_id=self.user.company_id, project_id=p.id, installer_id=installer_id))
        return {"id": str(p.id), "name": p.name, "lifecycle_status": value(p.lifecycle_status), "health_status": value(p.health_status),
                "door_status_counts": counts, "total_doors": len(doors), "open_issues": issues,
                "source": self._source("project", p.id, p.name, f"/installer/projects/{p.id}")}

    def _door_item(self, uow, d, reason_name, door_type_name, issue=None):
        return {"id": str(d.id), "door_id": str(d.id), "project_id": str(d.project_id), "unit_label": d.unit_label,
                "door_code": d.door_code, "house_number": d.house_number, "floor_label": d.floor_label,
                "apartment_number": d.apartment_number, "status": value(d.status), "version": d.version,
                "is_locked": d.is_locked, "reason_name": reason_name, "door_type_name": door_type_name,
                "installed_at": d.installed_at.isoformat() if d.installed_at else None,
                "comment": {"untrusted_text": d.comment},
                "issue": {"id": str(issue.id), "status": value(issue.status), "workflow_state": value(issue.workflow_state),
                          "title": {"untrusted_text": issue.title}} if issue is not None else None,
                "source": self._source("door", d.id, d.unit_label, f"/installer/projects/{d.project_id}")}

    def _names(self, uow, doors):
        reason_ids = {d.reason_id for d in doors if d.reason_id}
        type_ids = {d.door_type_id for d in doors if d.door_type_id}
        reasons = {r.id: r.name for r in uow.session.scalars(select(ReasonORM).where(
            ReasonORM.company_id == self.user.company_id, ReasonORM.id.in_(reason_ids))).all()} if reason_ids else {}
        types = {t.id: t.name for t in uow.session.scalars(select(DoorTypeORM).where(
            DoorTypeORM.company_id == self.user.company_id, DoorTypeORM.id.in_(type_ids))).all()} if type_ids else {}
        return reasons, types

    def _my_project_doors(self, uow, args):
        installer_id = require_installer_id(uow, self.user)
        p = self._my_project(uow, args.project_id, installer_id)
        doors = uow.doors.list_by_project_for_installer(company_id=self.user.company_id, project_id=p.id, installer_id=installer_id)
        if args.status:
            doors = [d for d in doors if value(d.status) == args.status]
        page = doors[args.offset:args.offset + args.limit + 1]
        reasons, types = self._names(uow, page[:args.limit])
        items = [self._door_item(uow, d, reasons.get(d.reason_id), types.get(d.door_type_id)) for d in page[:args.limit]]
        return {"items": items, "has_more": len(page) > args.limit, "offset": args.offset}

    def _my_door(self, uow, args):
        installer_id = require_installer_id(uow, self.user)
        d = uow.doors.get(company_id=self.user.company_id, door_id=args.door_id, active_project_only=True)
        if d is None or d.installer_id != installer_id:
            raise NotFound("Door not found")
        reasons, types = self._names(uow, [d])
        issue = uow.issues.get_by_door(company_id=self.user.company_id, door_id=d.id)
        item = self._door_item(uow, d, reasons.get(d.reason_id), types.get(d.door_type_id), issue)
        p = self._project(uow, d.project_id)
        item["project_name"] = p.name
        return item

    def _my_project_issues(self, uow, args):
        installer_id = require_installer_id(uow, self.user)
        p = self._my_project(uow, args.project_id, installer_id)
        rows = uow.issues.list_open_by_project_for_installer(company_id=self.user.company_id, project_id=p.id,
                                                             installer_id=installer_id, include_closed=True)
        if args.status:
            rows = [i for i in rows if value(i.status) == args.status]
        page = rows[args.offset:args.offset + args.limit + 1]
        labels = {d.id: d.unit_label for d in uow.doors.list_by_project_for_installer(
            company_id=self.user.company_id, project_id=p.id, installer_id=installer_id)}
        items = [{"id": str(i.id), "door_id": str(i.door_id), "unit_label": labels.get(i.door_id),
                  "title": {"untrusted_text": i.title}, "details": {"untrusted_text": i.details}, "status": value(i.status),
                  "workflow_state": value(i.workflow_state), "priority": value(i.priority),
                  "due_at": i.due_at.isoformat() if i.due_at else None,
                  "source": self._source("issue", i.id, i.title or labels.get(i.door_id) or "issue",
                                         f"/installer/issues?project_id={p.id}&issue_id={i.id}")}
                 for i in page[:args.limit]]
        return {"items": items, "has_more": len(page) > args.limit, "offset": args.offset}

    def _my_issue(self, uow, args):
        installer_id = require_installer_id(uow, self.user)
        try:
            i, d = InstallerIssuesApiService.ensure_issue_visible(uow, company_id=self.user.company_id, installer_id=installer_id,
                                                                  user_id=self.user.id, issue_id=args.issue_id)
        except DoorNotAssigned:
            raise NotFound("Issue not found") from None
        p = self._project(uow, d.project_id)
        comments = IssueCommentsService.list_comments(uow, company_id=self.user.company_id, issue_id=i.id)
        return {"id": str(i.id), "issue_id": str(i.id), "door_id": str(d.id), "unit_label": d.unit_label,
                "project_id": str(p.id), "project_name": p.name, "door_status": value(d.status),
                "status": value(i.status), "workflow_state": value(i.workflow_state), "priority": value(i.priority),
                "due_at": i.due_at.isoformat() if i.due_at else None,
                "updated_at": i.updated_at.isoformat() if i.updated_at else None,
                "title": {"untrusted_text": i.title}, "details": {"untrusted_text": i.details},
                "comments": [{"author": c.author_name, "created_at": c.created_at.isoformat() if c.created_at else None,
                              "body": {"untrusted_text": c.body}} for c in comments[-20:]],
                "source": self._source("issue", i.id, i.title or d.unit_label, f"/installer/issues?project_id={p.id}&issue_id={i.id}")}

    # ---- calendar, journals, workload --------------------------------------------------------------

    @staticmethod
    def _range(args):
        try:
            start = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end = datetime.strptime(args.to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            raise ValidationError("from_date and to_date must be calendar dates") from None
        if end <= start or (end - start).days > 62:
            raise ValidationError("The range must cover 1 to 62 days")
        return start, end

    def _event_items(self, uow, rows, *, with_assignees=True):
        counts = {}
        if with_assignees and rows:
            counts = dict(uow.session.execute(select(CalendarEventAssigneeORM.event_id, func.count(CalendarEventAssigneeORM.id))
                .where(CalendarEventAssigneeORM.company_id == self.user.company_id,
                       CalendarEventAssigneeORM.event_id.in_([e.id for e in rows])).group_by(CalendarEventAssigneeORM.event_id)).all())
        items = []
        for e in rows:
            item = {"id": str(e.id), "event_type": value(e.event_type), "starts_at": e.starts_at.isoformat(), "ends_at": e.ends_at.isoformat(),
                    "project_id": str(e.project_id) if e.project_id else None,
                    "title": {"untrusted_text": e.title}, "location": {"untrusted_text": e.location}}
            if with_assignees:
                item["assignees"] = int(counts.get(e.id, 0))
            if e.project_id:
                p = uow.projects.get(company_id=self.user.company_id, project_id=e.project_id)
                if p is not None:
                    path = f"/installer/projects/{p.id}" if self.user.role == "INSTALLER" else f"/projects?project_id={p.id}"
                    item["project_name"] = p.name
                    item["source"] = self._source("project", p.id, p.name, path)
            items.append(item)
        return items

    def _list_calendar_events(self, uow, args):
        start, end = self._range(args)
        if args.project_id:
            self._project(uow, args.project_id)
        rows = CalendarRepository(uow.session).list_range(company_id=self.user.company_id, starts_at=start, ends_at=end,
                                       project_id=args.project_id, limit=200)
        return {"items": self._event_items(uow, rows), "count": len(rows), "truncated": len(rows) >= 200}

    def _my_schedule(self, uow, args):
        installer_id = require_installer_id(uow, self.user)
        start, end = self._range(args)
        rows = CalendarRepository(uow.session).list_range(company_id=self.user.company_id, starts_at=start, ends_at=end,
                                       installer_id=installer_id, limit=200)
        return {"items": self._event_items(uow, rows, with_assignees=False), "count": len(rows), "truncated": len(rows) >= 200}

    def _project_journals(self, uow, args):
        p = self._project(uow, args.project_id)
        rows = uow.session.scalars(select(JournalORM).where(JournalORM.company_id == self.user.company_id, JournalORM.project_id == p.id)
                                   .order_by(JournalORM.created_at.desc()).limit(50)).all()
        return {"project_id": str(p.id), "project_name": p.name,
                "items": [{"id": str(j.id), "status": value(j.status), "title": {"untrusted_text": j.title},
                           "signed": j.signed_at is not None, "signed_at": j.signed_at.isoformat() if j.signed_at else None,
                           "snapshot_version": j.snapshot_version, "email_delivery_status": value(j.email_delivery_status),
                           "whatsapp_delivery_status": value(j.whatsapp_delivery_status),
                           "created_at": j.created_at.isoformat() if j.created_at else None} for j in rows],
                "source": self._source("project", p.id, p.name, f"/projects?project_id={p.id}")}

    def _installer_workload(self, uow, args):
        i = uow.session.get(InstallerORM, args.installer_id)
        if i is None or i.company_id != self.user.company_id or i.deleted_at is not None:
            raise NotFound("Installer not found")
        counts = uow.session.execute(select(DoorORM.status, func.count(DoorORM.id)).where(
            DoorORM.company_id == self.user.company_id, DoorORM.installer_id == i.id).group_by(DoorORM.status)).all()
        projects = uow.session.scalar(select(func.count(func.distinct(DoorORM.project_id))).where(
            DoorORM.company_id == self.user.company_id, DoorORM.installer_id == i.id))
        issues = uow.session.scalar(select(func.count(IssueORM.id)).join(DoorORM, DoorORM.id == IssueORM.door_id).where(
            IssueORM.company_id == self.user.company_id, DoorORM.company_id == self.user.company_id,
            DoorORM.installer_id == i.id, IssueORM.status == "OPEN"))
        return {"id": str(i.id), "full_name": i.full_name, "status": i.status, "is_active": i.is_active,
                "door_status_counts": {value(status): count for status, count in counts},
                "total_doors": sum(count for _, count in counts), "projects": int(projects or 0), "open_issues": int(issues or 0),
                "source": self._source("installer", i.id, i.full_name, f"/installers?installer_id={i.id}")}
