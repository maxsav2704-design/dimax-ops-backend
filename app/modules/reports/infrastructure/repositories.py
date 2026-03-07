from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.modules.addons.infrastructure.models import (
    AddonTypeORM,
    ProjectAddonFactORM,
    ProjectAddonPlanORM,
)
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.calendar.domain.enums import CalendarEventType
from app.modules.calendar.infrastructure.models import (
    CalendarEventAssigneeORM,
    CalendarEventORM,
)
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.issues.domain.enums import (
    IssuePriority,
    IssueStatus,
    IssueWorkflowState,
)
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.outbox.domain.enums import (
    DeliveryStatus,
    OutboxChannel,
    OutboxStatus,
)
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectImportRunORM, ProjectORM
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.modules.reasons.infrastructure.models import ReasonORM


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


def _payload_int(payload: dict | None, key: str, default: int = 0) -> int:
    if not isinstance(payload, dict):
        return default
    try:
        return int(payload.get(key, default))
    except (TypeError, ValueError):
        return default


def _payload_errors_count(payload: dict | None) -> int:
    if not isinstance(payload, dict):
        return 0
    errors = payload.get("errors")
    if isinstance(errors, list):
        return len(errors)
    return _payload_int(payload, "errors_count", 0)


def _payload_first_error(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    errors = payload.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first = errors[0]
    if isinstance(first, dict):
        text = str(first.get("message") or "").strip()
        return text[:300] or None
    text = str(first).strip()
    return text[:300] or None


def _import_run_status(run: ProjectImportRunORM) -> str:
    mode = str(run.import_mode or "")
    payload = run.result_payload if isinstance(run.result_payload, dict) else {}
    imported = _payload_int(payload, "imported", 0)
    errors_count = _payload_errors_count(payload)
    if mode == "analyze":
        return "ANALYZED"
    if imported <= 0 and errors_count > 0:
        return "FAILED"
    if imported > 0 and errors_count > 0:
        return "PARTIAL"
    if imported > 0:
        return "SUCCESS"
    return "EMPTY"


def _dispatcher_installer_availability_band(
    *,
    is_active: bool,
    status: str | None,
    active_projects: int,
    assigned_open_doors: int,
    next_event_at: datetime | None,
    now: datetime,
) -> str:
    status_value = str(status or "").upper()
    if not is_active or status_value == "INACTIVE":
        return "INACTIVE"
    if (
        status_value == "BUSY"
        or active_projects >= 4
        or assigned_open_doors >= 20
        or (
            next_event_at is not None
            and next_event_at <= (now + timedelta(hours=24))
        )
    ):
        return "BUSY"
    return "AVAILABLE"


def _dispatcher_project_status(
    *,
    pending_doors: int,
    blocked_issues: int,
    unassigned_doors: int,
    open_issues: int,
) -> str:
    if pending_doors <= 0:
        return "DONE"
    if blocked_issues > 0:
        return "BLOCKED"
    if unassigned_doors > 0:
        return "UNASSIGNED"
    if open_issues > 0:
        return "AT_RISK"
    return "READY"


class ReportsRepository:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _allowed_audit_catalog_entities() -> set[str]:
        return {"door_type", "reason", "company", "project", "installer_rate"}

    @staticmethod
    def _allowed_audit_catalog_actions() -> set[str]:
        return {
            "DOOR_TYPE_CREATE",
            "DOOR_TYPE_UPDATE",
            "DOOR_TYPE_DELETE",
            "REASON_CREATE",
            "REASON_UPDATE",
            "REASON_DELETE",
            "SETTINGS_COMPANY_UPDATE",
            "PROJECT_DOORS_IMPORT_ANALYZE",
            "PROJECT_DOORS_IMPORT_APPLY",
            "PROJECT_DOORS_IMPORT_RETRY",
            "PROJECT_DOORS_IMPORT_RETRY_BULK",
            "INSTALLER_RATE_CREATE",
            "INSTALLER_RATE_UPDATE",
            "INSTALLER_RATE_DELETE",
        }

    @staticmethod
    def _allowed_audit_issue_actions() -> set[str]:
        return {
            "ISSUE_STATUS_UPDATE",
            "ISSUE_WORKFLOW_UPDATE",
            "ISSUE_WORKFLOW_BULK_UPDATE",
        }

    @staticmethod
    def _allowed_audit_installer_rate_actions() -> set[str]:
        return {
            "INSTALLER_RATE_CREATE",
            "INSTALLER_RATE_UPDATE",
            "INSTALLER_RATE_DELETE",
        }

    def _audit_catalog_query(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        entity_type: str | None,
        action: str | None,
    ):
        q = self.session.query(AuditLogORM).filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type.in_(self._allowed_audit_catalog_entities()),
            AuditLogORM.action.in_(self._allowed_audit_catalog_actions()),
        )
        if date_from is not None:
            q = q.filter(AuditLogORM.created_at >= date_from)
        if date_to is not None:
            q = q.filter(AuditLogORM.created_at < date_to)
        if entity_type is not None:
            q = q.filter(AuditLogORM.entity_type == entity_type)
        if action is not None:
            q = q.filter(AuditLogORM.action == action)
        return q

    def _audit_issue_query(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        issue_id: uuid.UUID | None,
    ):
        q = self.session.query(AuditLogORM).filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type == "issue",
            AuditLogORM.action.in_(self._allowed_audit_issue_actions()),
        )
        if date_from is not None:
            q = q.filter(AuditLogORM.created_at >= date_from)
        if date_to is not None:
            q = q.filter(AuditLogORM.created_at < date_to)
        if action is not None:
            q = q.filter(AuditLogORM.action == action)
        if issue_id is not None:
            q = q.filter(AuditLogORM.entity_id == issue_id)
        return q

    def _audit_installer_rate_query(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        rate_id: uuid.UUID | None,
    ):
        q = self.session.query(AuditLogORM).filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type == "installer_rate",
            AuditLogORM.action.in_(self._allowed_audit_installer_rate_actions()),
        )
        if date_from is not None:
            q = q.filter(AuditLogORM.created_at >= date_from)
        if date_to is not None:
            q = q.filter(AuditLogORM.created_at < date_to)
        if action is not None:
            q = q.filter(AuditLogORM.action == action)
        if rate_id is not None:
            q = q.filter(AuditLogORM.entity_id == rate_id)
        return q

    def kpi(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> dict:
        installed_filter = [DoorORM.status == DoorStatus.INSTALLED]
        if date_from is not None:
            installed_filter.append(DoorORM.installed_at >= date_from)
        if date_to is not None:
            installed_filter.append(DoorORM.installed_at < date_to)

        installed_doors = (
            self.session.query(func.count(DoorORM.id))
            .filter(DoorORM.company_id == company_id, *installed_filter)
            .scalar()
        ) or 0

        not_installed_doors = (
            self.session.query(func.count(DoorORM.id))
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.status == DoorStatus.NOT_INSTALLED,
            )
            .scalar()
        ) or 0

        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )
        effective_installer_rate = func.coalesce(
            DoorORM.installer_rate_snapshot,
            InstallerRateORM.price,
            0,
        )

        q_money = (
            self.session.query(
                func.coalesce(func.sum(DoorORM.our_price), 0).label("revenue"),
                func.coalesce(func.sum(effective_installer_rate), 0).label("payroll"),
                func.coalesce(
                    func.sum(
                        DoorORM.our_price - effective_installer_rate
                    ),
                    0,
                ).label("profit"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    DoorORM.installer_rate_snapshot.is_(None),
                                    InstallerRateORM.id.is_(None),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing_rates"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(DoorORM.company_id == company_id, *installed_filter)
        )

        row = q_money.one()
        revenue_total = _dec(row.revenue)
        payroll_total = _dec(row.payroll)
        profit_total = _dec(row.profit)
        missing_rates = int(row.missing_rates or 0)

        addon_filter = [ProjectAddonFactORM.company_id == company_id]
        if date_from is not None:
            addon_filter.append(ProjectAddonFactORM.done_at >= date_from)
        if date_to is not None:
            addon_filter.append(ProjectAddonFactORM.done_at < date_to)

        plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id == ProjectAddonFactORM.addon_type_id,
        )

        addon_row = (
            self.session.query(
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("addon_revenue"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                    ),
                    0,
                ).label("addon_payroll"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * (
                            func.coalesce(ProjectAddonPlanORM.client_price, 0)
                            - func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                        )
                    ),
                    0,
                ).label("addon_profit"),
                func.coalesce(
                    func.sum(
                        case(
                            (ProjectAddonPlanORM.id.is_(None), 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("addon_missing_plan"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, plan_join)
            .filter(*addon_filter)
            .one()
        )

        revenue_total += _dec(addon_row.addon_revenue)
        payroll_total += _dec(addon_row.addon_payroll)
        profit_total += _dec(addon_row.addon_profit)
        addon_missing_plan = int(addon_row.addon_missing_plan or 0)

        problem_projects = (
            self.session.query(func.count(ProjectORM.id))
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.deleted_at.is_(None),
                ProjectORM.status == ProjectStatus.PROBLEM,
            )
            .scalar()
        ) or 0

        return {
            "installed_doors": int(installed_doors),
            "not_installed_doors": int(not_installed_doors),
            "revenue_total": revenue_total,
            "payroll_total": payroll_total,
            "profit_total": profit_total,
            "problem_projects": int(problem_projects),
            "missing_rates_installed_doors": missing_rates,
            "missing_addon_plans_done": addon_missing_plan,
        }

    def problem_projects(
        self,
        *,
        company_id: uuid.UUID,
        limit: int = 50,
    ) -> list[dict]:
        sub = (
            self.session.query(
                DoorORM.project_id.label("project_id"),
                func.count(DoorORM.id).label("not_installed_doors"),
            )
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.status == DoorStatus.NOT_INSTALLED,
            )
            .group_by(DoorORM.project_id)
            .subquery()
        )

        rows = (
            self.session.query(
                ProjectORM.id,
                ProjectORM.name,
                ProjectORM.address,
                func.coalesce(sub.c.not_installed_doors, 0).label(
                    "not_installed_doors"
                ),
            )
            .outerjoin(sub, sub.c.project_id == ProjectORM.id)
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.deleted_at.is_(None),
            )
            .filter(func.coalesce(sub.c.not_installed_doors, 0) > 0)
            .order_by(
                func.coalesce(sub.c.not_installed_doors, 0).desc(),
                ProjectORM.created_at.desc(),
            )
            .limit(limit)
            .all()
        )

        return [
            {
                "project_id": r.id,
                "name": r.name,
                "address": r.address,
                "not_installed_doors": int(r.not_installed_doors),
            }
            for r in rows
        ]

    def dispatcher_board(
        self,
        *,
        company_id: uuid.UUID,
        now: datetime,
        projects_limit: int = 8,
        installers_limit: int = 8,
        recommendation_limit: int = 3,
    ) -> dict:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        project_rows = (
            self.session.query(
                ProjectORM.id.label("project_id"),
                ProjectORM.name.label("project_name"),
                ProjectORM.address.label("address"),
                ProjectORM.status.label("project_status"),
                ProjectORM.contact_name.label("contact_name"),
                func.count(DoorORM.id).label("total_doors"),
                func.coalesce(
                    func.sum(
                        case((DoorORM.status == DoorStatus.INSTALLED, 1), else_=0)
                    ),
                    0,
                ).label("installed_doors"),
                func.coalesce(
                    func.sum(
                        case((DoorORM.status == DoorStatus.NOT_INSTALLED, 1), else_=0)
                    ),
                    0,
                ).label("pending_doors"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    DoorORM.status == DoorStatus.NOT_INSTALLED,
                                    DoorORM.installer_id.is_not(None),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("assigned_open_doors"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    DoorORM.status == DoorStatus.NOT_INSTALLED,
                                    DoorORM.installer_id.is_(None),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("unassigned_doors"),
            )
            .select_from(ProjectORM)
            .outerjoin(
                DoorORM,
                and_(
                    DoorORM.project_id == ProjectORM.id,
                    DoorORM.company_id == ProjectORM.company_id,
                ),
            )
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.deleted_at.is_(None),
            )
            .group_by(
                ProjectORM.id,
                ProjectORM.name,
                ProjectORM.address,
                ProjectORM.status,
                ProjectORM.contact_name,
            )
            .all()
        )

        issue_rows = (
            self.session.query(
                DoorORM.project_id.label("project_id"),
                func.count(IssueORM.id).label("open_issues"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                IssueORM.workflow_state == IssueWorkflowState.BLOCKED,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("blocked_issues"),
            )
            .select_from(IssueORM)
            .join(
                DoorORM,
                and_(
                    DoorORM.id == IssueORM.door_id,
                    DoorORM.company_id == IssueORM.company_id,
                ),
            )
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.status == IssueStatus.OPEN,
            )
            .group_by(DoorORM.project_id)
            .all()
        )
        issues_by_project = {
            row.project_id: {
                "open_issues": int(row.open_issues or 0),
                "blocked_issues": int(row.blocked_issues or 0),
            }
            for row in issue_rows
        }

        project_event_rows = (
            self.session.query(
                CalendarEventORM.project_id,
                CalendarEventORM.title,
                CalendarEventORM.starts_at,
            )
            .filter(
                CalendarEventORM.company_id == company_id,
                CalendarEventORM.project_id.is_not(None),
                CalendarEventORM.starts_at >= now,
            )
            .order_by(
                CalendarEventORM.project_id.asc(),
                CalendarEventORM.starts_at.asc(),
            )
            .all()
        )
        next_event_by_project: dict[uuid.UUID, dict] = {}
        for row in project_event_rows:
            project_id = row.project_id
            if project_id is None or project_id in next_event_by_project:
                continue
            next_event_by_project[project_id] = {
                "next_visit_at": row.starts_at,
                "next_visit_title": row.title,
            }

        installer_rows = (
            self.session.query(
                InstallerORM.id.label("installer_id"),
                InstallerORM.full_name.label("installer_name"),
                InstallerORM.status.label("status"),
                InstallerORM.is_active.label("is_active"),
                InstallerORM.phone.label("phone"),
                InstallerORM.email.label("email"),
            )
            .filter(
                InstallerORM.company_id == company_id,
                InstallerORM.deleted_at.is_(None),
            )
            .all()
        )

        installer_door_rows = (
            self.session.query(
                DoorORM.installer_id.label("installer_id"),
                func.count(
                    case((DoorORM.status == DoorStatus.NOT_INSTALLED, 1), else_=None)
                ).label("assigned_open_doors"),
                func.count(
                    func.distinct(
                        case(
                            (
                                DoorORM.status == DoorStatus.NOT_INSTALLED,
                                DoorORM.project_id,
                            ),
                            else_=None,
                        )
                    )
                ).label("active_projects"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    IssueORM.id.is_not(None),
                                    IssueORM.status == IssueStatus.OPEN,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("open_issues"),
            )
            .select_from(DoorORM)
            .outerjoin(
                IssueORM,
                and_(
                    IssueORM.door_id == DoorORM.id,
                    IssueORM.company_id == DoorORM.company_id,
                ),
            )
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.installer_id.is_not(None),
            )
            .group_by(DoorORM.installer_id)
            .all()
        )
        installer_doors_by_id = {
            row.installer_id: {
                "assigned_open_doors": int(row.assigned_open_doors or 0),
                "active_projects": int(row.active_projects or 0),
                "open_issues": int(row.open_issues or 0),
            }
            for row in installer_door_rows
            if row.installer_id is not None
        }

        installer_event_rows = (
            self.session.query(
                CalendarEventAssigneeORM.installer_id.label("installer_id"),
                CalendarEventORM.title.label("title"),
                CalendarEventORM.starts_at.label("starts_at"),
            )
            .select_from(CalendarEventAssigneeORM)
            .join(
                CalendarEventORM,
                and_(
                    CalendarEventORM.id == CalendarEventAssigneeORM.event_id,
                    CalendarEventORM.company_id == CalendarEventAssigneeORM.company_id,
                ),
            )
            .filter(
                CalendarEventAssigneeORM.company_id == company_id,
                CalendarEventORM.starts_at >= now,
            )
            .order_by(
                CalendarEventAssigneeORM.installer_id.asc(),
                CalendarEventORM.starts_at.asc(),
            )
            .all()
        )
        next_event_by_installer: dict[uuid.UUID, dict] = {}
        for row in installer_event_rows:
            installer_id = row.installer_id
            if installer_id in next_event_by_installer:
                continue
            next_event_by_installer[installer_id] = {
                "next_event_at": row.starts_at,
                "next_event_title": row.title,
            }

        installer_items: list[dict] = []
        for row in installer_rows:
            stats = installer_doors_by_id.get(row.installer_id, {})
            next_event = next_event_by_installer.get(row.installer_id, {})
            availability_band = _dispatcher_installer_availability_band(
                is_active=bool(row.is_active),
                status=row.status,
                active_projects=int(stats.get("active_projects", 0)),
                assigned_open_doors=int(stats.get("assigned_open_doors", 0)),
                next_event_at=next_event.get("next_event_at"),
                now=now,
            )
            installer_items.append(
                {
                    "installer_id": row.installer_id,
                    "installer_name": row.installer_name,
                    "status": str(row.status or ""),
                    "availability_band": availability_band,
                    "is_active": bool(row.is_active),
                    "phone": row.phone,
                    "email": row.email,
                    "active_projects": int(stats.get("active_projects", 0)),
                    "assigned_open_doors": int(stats.get("assigned_open_doors", 0)),
                    "open_issues": int(stats.get("open_issues", 0)),
                    "next_event_at": next_event.get("next_event_at"),
                    "next_event_title": next_event.get("next_event_title"),
                }
            )

        availability_order = {"AVAILABLE": 0, "BUSY": 1, "INACTIVE": 2}
        installer_items.sort(
            key=lambda item: (
                availability_order.get(item["availability_band"], 9),
                item["assigned_open_doors"],
                item["active_projects"],
                item["open_issues"],
                item["next_event_at"] is not None,
                item["next_event_at"] or now,
                item["installer_name"].lower(),
            )
        )

        recommendation_pool = [
            item for item in installer_items if item["availability_band"] != "INACTIVE"
        ]

        project_items: list[dict] = []
        for row in project_rows:
            issue_stats = issues_by_project.get(row.project_id, {})
            next_event = next_event_by_project.get(row.project_id, {})
            pending_doors = int(row.pending_doors or 0)
            blocked_issues = int(issue_stats.get("blocked_issues", 0))
            unassigned_doors = int(row.unassigned_doors or 0)
            open_issues = int(issue_stats.get("open_issues", 0))
            completion_pct = (
                round((int(row.installed_doors or 0) * 100.0) / int(row.total_doors or 1), 2)
                if int(row.total_doors or 0) > 0
                else 0.0
            )
            project_items.append(
                {
                    "project_id": row.project_id,
                    "project_name": row.project_name,
                    "address": row.address,
                    "project_status": (
                        row.project_status.value
                        if hasattr(row.project_status, "value")
                        else str(row.project_status)
                    ),
                    "dispatch_status": _dispatcher_project_status(
                        pending_doors=pending_doors,
                        blocked_issues=blocked_issues,
                        unassigned_doors=unassigned_doors,
                        open_issues=open_issues,
                    ),
                    "contact_name": row.contact_name,
                    "total_doors": int(row.total_doors or 0),
                    "installed_doors": int(row.installed_doors or 0),
                    "pending_doors": pending_doors,
                    "assigned_open_doors": int(row.assigned_open_doors or 0),
                    "unassigned_doors": unassigned_doors,
                    "open_issues": open_issues,
                    "blocked_issues": blocked_issues,
                    "completion_pct": completion_pct,
                    "next_visit_at": next_event.get("next_visit_at"),
                    "next_visit_title": next_event.get("next_visit_title"),
                    "recommended_installers": [
                        {
                            "installer_id": installer["installer_id"],
                            "installer_name": installer["installer_name"],
                            "availability_band": installer["availability_band"],
                            "active_projects": installer["active_projects"],
                            "assigned_open_doors": installer["assigned_open_doors"],
                            "open_issues": installer["open_issues"],
                            "next_event_at": installer["next_event_at"],
                        }
                        for installer in recommendation_pool[:recommendation_limit]
                    ],
                }
            )

        dispatch_order = {"BLOCKED": 0, "UNASSIGNED": 1, "AT_RISK": 2, "READY": 3, "DONE": 4}
        project_items.sort(
            key=lambda item: (
                dispatch_order.get(item["dispatch_status"], 9),
                -item["blocked_issues"],
                -item["unassigned_doors"],
                -item["pending_doors"],
                item["completion_pct"],
                item["project_name"].lower(),
            )
        )

        scheduled_visits_7d = int(
            self.session.query(func.count(CalendarEventORM.id))
            .filter(
                CalendarEventORM.company_id == company_id,
                CalendarEventORM.event_type == CalendarEventType.INSTALLATION,
                CalendarEventORM.starts_at >= now,
                CalendarEventORM.starts_at < (now + timedelta(days=7)),
            )
            .scalar()
            or 0
        )

        summary = {
            "total_projects": len(project_rows),
            "total_doors": sum(item["total_doors"] for item in project_items),
            "installed_doors": sum(item["installed_doors"] for item in project_items),
            "pending_doors": sum(item["pending_doors"] for item in project_items),
            "projects_needing_dispatch": sum(
                1 for item in project_items if item["dispatch_status"] != "DONE"
            ),
            "open_issues": sum(item["open_issues"] for item in project_items),
            "blocked_issues": sum(item["blocked_issues"] for item in project_items),
            "unassigned_doors": sum(item["unassigned_doors"] for item in project_items),
            "available_installers": sum(
                1 for item in installer_items if item["availability_band"] == "AVAILABLE"
            ),
            "busy_installers": sum(
                1 for item in installer_items if item["availability_band"] == "BUSY"
            ),
            "scheduled_visits_7d": scheduled_visits_7d,
        }

        return {
            "summary": summary,
            "projects": project_items[:projects_limit],
            "installers": installer_items[:installers_limit],
        }

    def top_reasons(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int = 10,
    ) -> list[dict]:
        q = self.session.query(
            DoorORM.reason_id.label("reason_id"),
            func.count(DoorORM.id).label("cnt"),
        ).filter(
            DoorORM.company_id == company_id,
            DoorORM.status == DoorStatus.NOT_INSTALLED,
        )
        if date_from is not None:
            q = q.filter(DoorORM.updated_at >= date_from)
        if date_to is not None:
            q = q.filter(DoorORM.updated_at < date_to)

        rows = (
            q.group_by(DoorORM.reason_id)
            .order_by(func.count(DoorORM.id).desc())
            .limit(limit)
            .all()
        )

        reason_ids = [r.reason_id for r in rows if r.reason_id is not None]
        names = {}
        if reason_ids:
            rr = (
                self.session.query(ReasonORM.id, ReasonORM.name)
                .filter(
                    ReasonORM.company_id == company_id,
                    ReasonORM.id.in_(reason_ids),
                )
                .all()
            )
            names = {x.id: x.name for x in rr}

        result = []
        for r in rows:
            rid = r.reason_id
            result.append(
                {
                    "reason_id": rid,
                    "reason_name": (
                        names.get(rid, "No reason") if rid else "No reason"
                    ),
                    "count": int(r.cnt),
                }
            )
        return result

    def installers_kpi(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int = 200,
        offset: int = 0,
        sort_by: str = "installed_doors",
        sort_dir: str = "desc",
    ) -> list[dict]:
        installed_filter = [DoorORM.status == DoorStatus.INSTALLED]
        if date_from is not None:
            installed_filter.append(DoorORM.installed_at >= date_from)
        if date_to is not None:
            installed_filter.append(DoorORM.installed_at < date_to)

        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )
        effective_installer_rate = func.coalesce(
            DoorORM.installer_rate_snapshot,
            InstallerRateORM.price,
            0,
        )
        installed_doors_expr = func.count(DoorORM.id)
        revenue_total_expr = func.coalesce(func.sum(DoorORM.our_price), 0)
        payroll_total_expr = func.coalesce(func.sum(effective_installer_rate), 0)
        profit_total_expr = func.coalesce(
            func.sum(DoorORM.our_price - effective_installer_rate),
            0,
        )
        missing_rates_expr = func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            DoorORM.installer_rate_snapshot.is_(None),
                            InstallerRateORM.id.is_(None),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        )
        sort_map = {
            "installed_doors": installed_doors_expr,
            "payroll_total": payroll_total_expr,
            "revenue_total": revenue_total_expr,
            "profit_total": profit_total_expr,
            "installer_name": InstallerORM.full_name,
        }
        sort_expr = sort_map.get(sort_by, installed_doors_expr)
        sort_clause = sort_expr.asc() if sort_dir == "asc" else sort_expr.desc()
        order_clauses = [sort_clause]
        if sort_by != "installer_name":
            order_clauses.append(InstallerORM.full_name.asc())
        order_clauses.append(InstallerORM.id.asc())

        rows = (
            self.session.query(
                InstallerORM.id.label("installer_id"),
                InstallerORM.full_name.label("installer_name"),
                installed_doors_expr.label("installed_doors"),
                revenue_total_expr.label("revenue_total"),
                payroll_total_expr.label("payroll_total"),
                profit_total_expr.label("profit_total"),
                missing_rates_expr.label("missing_rates"),
            )
            .select_from(DoorORM)
            .join(
                InstallerORM,
                and_(
                    InstallerORM.company_id == DoorORM.company_id,
                    InstallerORM.id == DoorORM.installer_id,
                ),
            )
            .outerjoin(InstallerRateORM, rate_join)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.installer_id.isnot(None),
                *installed_filter,
            )
            .group_by(InstallerORM.id, InstallerORM.full_name)
            .order_by(*order_clauses)
            .limit(limit)
            .offset(offset)
            .all()
        )

        return [
            {
                "installer_id": row.installer_id,
                "installer_name": row.installer_name,
                "installed_doors": int(row.installed_doors or 0),
                "payroll_total": _dec(row.payroll_total),
                "revenue_total": _dec(row.revenue_total),
                "profit_total": _dec(row.profit_total),
                "missing_rates_installed_doors": int(row.missing_rates or 0),
            }
            for row in rows
        ]

    def installer_profitability_matrix(
        self,
        *,
        company_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "profit_total",
        sort_dir: str = "desc",
    ) -> dict:
        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )
        effective_installer_rate = func.coalesce(
            DoorORM.installer_rate_snapshot,
            InstallerRateORM.price,
            0,
        )

        door_sub = (
            self.session.query(
                DoorORM.installer_id.label("installer_id"),
                func.count(DoorORM.id).label("installed_doors"),
                func.count(func.distinct(DoorORM.project_id)).label("active_projects"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label("revenue_total"),
                func.coalesce(func.sum(effective_installer_rate), 0).label("payroll_total"),
                func.coalesce(
                    func.sum(DoorORM.our_price - effective_installer_rate),
                    0,
                ).label("profit_total"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    DoorORM.installer_rate_snapshot.is_(None),
                                    InstallerRateORM.id.is_(None),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing_rates_installed_doors"),
                func.max(DoorORM.installed_at).label("last_installed_at"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.installer_id.isnot(None),
                DoorORM.status == DoorStatus.INSTALLED,
            )
            .group_by(DoorORM.installer_id)
            .subquery()
        )

        issue_sub = (
            self.session.query(
                DoorORM.installer_id.label("installer_id"),
                func.count(IssueORM.id).label("open_issues"),
            )
            .select_from(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.status == IssueStatus.OPEN,
                DoorORM.installer_id.isnot(None),
            )
            .group_by(DoorORM.installer_id)
            .subquery()
        )

        addon_plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id == ProjectAddonFactORM.addon_type_id,
        )
        addon_sub = (
            self.session.query(
                ProjectAddonFactORM.installer_id.label("installer_id"),
                func.coalesce(func.sum(ProjectAddonFactORM.qty_done), 0).label("addons_done_qty"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("addon_revenue_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                    ),
                    0,
                ).label("addon_payroll_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * (
                            func.coalesce(ProjectAddonPlanORM.client_price, 0)
                            - func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                        )
                    ),
                    0,
                ).label("addon_profit_total"),
                func.coalesce(
                    func.sum(case((ProjectAddonPlanORM.id.is_(None), 1), else_=0)),
                    0,
                ).label("missing_addon_plans_facts"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, addon_plan_join)
            .filter(
                ProjectAddonFactORM.company_id == company_id,
                ProjectAddonFactORM.installer_id.isnot(None),
            )
            .group_by(ProjectAddonFactORM.installer_id)
            .subquery()
        )

        revenue_expr = func.coalesce(door_sub.c.revenue_total, 0) + func.coalesce(
            addon_sub.c.addon_revenue_total, 0
        )
        payroll_expr = func.coalesce(door_sub.c.payroll_total, 0) + func.coalesce(
            addon_sub.c.addon_payroll_total, 0
        )
        profit_expr = func.coalesce(door_sub.c.profit_total, 0) + func.coalesce(
            addon_sub.c.addon_profit_total, 0
        )
        installed_doors_expr = func.coalesce(door_sub.c.installed_doors, 0)
        margin_expr = case(
            (revenue_expr > 0, (profit_expr * 100.0 / revenue_expr)),
            else_=0.0,
        )
        avg_profit_per_door_expr = case(
            (installed_doors_expr > 0, (profit_expr / installed_doors_expr)),
            else_=0,
        )
        open_issues_expr = func.coalesce(issue_sub.c.open_issues, 0)

        base_query = (
            self.session.query(
                InstallerORM.id.label("installer_id"),
                InstallerORM.full_name.label("installer_name"),
                installed_doors_expr.label("installed_doors"),
                func.coalesce(door_sub.c.active_projects, 0).label("active_projects"),
                open_issues_expr.label("open_issues"),
                func.coalesce(addon_sub.c.addons_done_qty, 0).label("addons_done_qty"),
                revenue_expr.label("revenue_total"),
                payroll_expr.label("payroll_total"),
                profit_expr.label("profit_total"),
                margin_expr.label("margin_pct"),
                avg_profit_per_door_expr.label("avg_profit_per_door"),
                func.coalesce(
                    door_sub.c.missing_rates_installed_doors,
                    0,
                ).label("missing_rates_installed_doors"),
                func.coalesce(
                    addon_sub.c.missing_addon_plans_facts,
                    0,
                ).label("missing_addon_plans_facts"),
                door_sub.c.last_installed_at.label("last_installed_at"),
            )
            .select_from(InstallerORM)
            .outerjoin(door_sub, door_sub.c.installer_id == InstallerORM.id)
            .outerjoin(issue_sub, issue_sub.c.installer_id == InstallerORM.id)
            .outerjoin(addon_sub, addon_sub.c.installer_id == InstallerORM.id)
            .filter(
                InstallerORM.company_id == company_id,
                or_(
                    func.coalesce(door_sub.c.installed_doors, 0) > 0,
                    func.coalesce(addon_sub.c.addons_done_qty, 0) > 0,
                ),
            )
        )

        total = int(
            base_query.with_entities(func.count(InstallerORM.id)).scalar() or 0
        )

        sort_map = {
            "profit_total": profit_expr,
            "margin_pct": margin_expr,
            "installed_doors": installed_doors_expr,
            "avg_profit_per_door": avg_profit_per_door_expr,
            "open_issues": open_issues_expr,
        }
        sort_expr = sort_map.get(sort_by, profit_expr)
        sort_clause = sort_expr.asc() if sort_dir == "asc" else sort_expr.desc()

        rows = (
            base_query.order_by(sort_clause, InstallerORM.full_name.asc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        items: list[dict] = []
        for row in rows:
            profit_total = _dec(row.profit_total)
            margin_pct = round(float(row.margin_pct or 0), 2)
            open_issues = int(row.open_issues or 0)
            if profit_total <= 0 or margin_pct < 15 or open_issues >= 5:
                performance_band = "RISK"
            elif margin_pct >= 35 and profit_total >= Decimal("300") and open_issues <= 1:
                performance_band = "STRONG"
            else:
                performance_band = "WATCH"

            items.append(
                {
                    "installer_id": row.installer_id,
                    "installer_name": row.installer_name,
                    "performance_band": performance_band,
                    "installed_doors": int(row.installed_doors or 0),
                    "active_projects": int(row.active_projects or 0),
                    "open_issues": open_issues,
                    "addons_done_qty": _dec(row.addons_done_qty),
                    "revenue_total": _dec(row.revenue_total),
                    "payroll_total": _dec(row.payroll_total),
                    "profit_total": profit_total,
                    "margin_pct": margin_pct,
                    "avg_profit_per_door": _dec(row.avg_profit_per_door),
                    "missing_rates_installed_doors": int(
                        row.missing_rates_installed_doors or 0
                    ),
                    "missing_addon_plans_facts": int(
                        row.missing_addon_plans_facts or 0
                    ),
                    "last_installed_at": row.last_installed_at,
                }
            )

        return {
            "total": total,
            "items": items,
        }

    def installer_project_profitability(
        self,
        *,
        company_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "profit_total",
        sort_dir: str = "desc",
    ) -> dict:
        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )
        effective_installer_rate = func.coalesce(
            DoorORM.installer_rate_snapshot,
            InstallerRateORM.price,
            0,
        )

        door_sub = (
            self.session.query(
                DoorORM.installer_id.label("installer_id"),
                DoorORM.project_id.label("project_id"),
                func.count(DoorORM.id).label("installed_doors"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label("revenue_total"),
                func.coalesce(func.sum(effective_installer_rate), 0).label("payroll_total"),
                func.coalesce(
                    func.sum(DoorORM.our_price - effective_installer_rate),
                    0,
                ).label("profit_total"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    DoorORM.installer_rate_snapshot.is_(None),
                                    InstallerRateORM.id.is_(None),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing_rates_installed_doors"),
                func.max(DoorORM.installed_at).label("last_installed_at"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.installer_id.isnot(None),
                DoorORM.status == DoorStatus.INSTALLED,
            )
            .group_by(DoorORM.installer_id, DoorORM.project_id)
            .subquery()
        )

        issue_sub = (
            self.session.query(
                DoorORM.installer_id.label("installer_id"),
                DoorORM.project_id.label("project_id"),
                func.count(IssueORM.id).label("open_issues"),
            )
            .select_from(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.status == IssueStatus.OPEN,
                DoorORM.installer_id.isnot(None),
            )
            .group_by(DoorORM.installer_id, DoorORM.project_id)
            .subquery()
        )

        addon_plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id == ProjectAddonFactORM.addon_type_id,
        )
        addon_sub = (
            self.session.query(
                ProjectAddonFactORM.installer_id.label("installer_id"),
                ProjectAddonFactORM.project_id.label("project_id"),
                func.coalesce(func.sum(ProjectAddonFactORM.qty_done), 0).label("addons_done_qty"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("addon_revenue_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                    ),
                    0,
                ).label("addon_payroll_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * (
                            func.coalesce(ProjectAddonPlanORM.client_price, 0)
                            - func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                        )
                    ),
                    0,
                ).label("addon_profit_total"),
                func.coalesce(
                    func.sum(case((ProjectAddonPlanORM.id.is_(None), 1), else_=0)),
                    0,
                ).label("missing_addon_plans_facts"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, addon_plan_join)
            .filter(
                ProjectAddonFactORM.company_id == company_id,
                ProjectAddonFactORM.installer_id.isnot(None),
            )
            .group_by(ProjectAddonFactORM.installer_id, ProjectAddonFactORM.project_id)
            .subquery()
        )

        revenue_expr = func.coalesce(door_sub.c.revenue_total, 0) + func.coalesce(
            addon_sub.c.addon_revenue_total, 0
        )
        payroll_expr = func.coalesce(door_sub.c.payroll_total, 0) + func.coalesce(
            addon_sub.c.addon_payroll_total, 0
        )
        profit_expr = func.coalesce(door_sub.c.profit_total, 0) + func.coalesce(
            addon_sub.c.addon_profit_total, 0
        )
        installed_doors_expr = func.coalesce(door_sub.c.installed_doors, 0)
        margin_expr = case(
            (revenue_expr > 0, (profit_expr * 100.0 / revenue_expr)),
            else_=0.0,
        )
        avg_profit_per_door_expr = case(
            (installed_doors_expr > 0, (profit_expr / installed_doors_expr)),
            else_=0,
        )
        open_issues_expr = func.coalesce(issue_sub.c.open_issues, 0)

        base_query = (
            self.session.query(
                InstallerORM.id.label("installer_id"),
                InstallerORM.full_name.label("installer_name"),
                ProjectORM.id.label("project_id"),
                ProjectORM.name.label("project_name"),
                installed_doors_expr.label("installed_doors"),
                open_issues_expr.label("open_issues"),
                func.coalesce(addon_sub.c.addons_done_qty, 0).label("addons_done_qty"),
                revenue_expr.label("revenue_total"),
                payroll_expr.label("payroll_total"),
                profit_expr.label("profit_total"),
                margin_expr.label("margin_pct"),
                avg_profit_per_door_expr.label("avg_profit_per_door"),
                func.coalesce(
                    door_sub.c.missing_rates_installed_doors,
                    0,
                ).label("missing_rates_installed_doors"),
                func.coalesce(
                    addon_sub.c.missing_addon_plans_facts,
                    0,
                ).label("missing_addon_plans_facts"),
                door_sub.c.last_installed_at.label("last_installed_at"),
            )
            .select_from(door_sub)
            .join(
                InstallerORM,
                and_(
                    InstallerORM.company_id == company_id,
                    InstallerORM.id == door_sub.c.installer_id,
                ),
            )
            .join(
                ProjectORM,
                and_(
                    ProjectORM.company_id == company_id,
                    ProjectORM.id == door_sub.c.project_id,
                ),
            )
            .outerjoin(
                issue_sub,
                and_(
                    issue_sub.c.installer_id == door_sub.c.installer_id,
                    issue_sub.c.project_id == door_sub.c.project_id,
                ),
            )
            .outerjoin(
                addon_sub,
                and_(
                    addon_sub.c.installer_id == door_sub.c.installer_id,
                    addon_sub.c.project_id == door_sub.c.project_id,
                ),
            )
        )

        total = int(base_query.with_entities(func.count()).scalar() or 0)

        sort_map = {
            "profit_total": profit_expr,
            "margin_pct": margin_expr,
            "installed_doors": installed_doors_expr,
            "open_issues": open_issues_expr,
            "avg_profit_per_door": avg_profit_per_door_expr,
        }
        sort_expr = sort_map.get(sort_by, profit_expr)
        sort_clause = sort_expr.asc() if sort_dir == "asc" else sort_expr.desc()

        rows = (
            base_query.order_by(sort_clause, ProjectORM.name.asc(), InstallerORM.full_name.asc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        items: list[dict] = []
        for row in rows:
            profit_total = _dec(row.profit_total)
            margin_pct = round(float(row.margin_pct or 0), 2)
            open_issues = int(row.open_issues or 0)
            if profit_total <= 0 or margin_pct < 15 or open_issues >= 3:
                performance_band = "RISK"
            elif margin_pct >= 30 and profit_total >= Decimal("150") and open_issues == 0:
                performance_band = "STRONG"
            else:
                performance_band = "WATCH"

            items.append(
                {
                    "installer_id": row.installer_id,
                    "installer_name": row.installer_name,
                    "project_id": row.project_id,
                    "project_name": row.project_name,
                    "performance_band": performance_band,
                    "installed_doors": int(row.installed_doors or 0),
                    "open_issues": open_issues,
                    "addons_done_qty": _dec(row.addons_done_qty),
                    "revenue_total": _dec(row.revenue_total),
                    "payroll_total": _dec(row.payroll_total),
                    "profit_total": profit_total,
                    "margin_pct": margin_pct,
                    "avg_profit_per_door": _dec(row.avg_profit_per_door),
                    "missing_rates_installed_doors": int(
                        row.missing_rates_installed_doors or 0
                    ),
                    "missing_addon_plans_facts": int(
                        row.missing_addon_plans_facts or 0
                    ),
                    "last_installed_at": row.last_installed_at,
                }
            )

        return {
            "total": total,
            "items": items,
        }

    def risk_concentration(
        self,
        *,
        company_id: uuid.UUID,
        limit: int = 5,
    ) -> dict:
        margin_risk = self.projects_margin(
            company_id=company_id,
            limit=limit,
            offset=0,
            sort_by="profit_total",
            sort_dir="asc",
        )
        order_risk = self.order_numbers_kpi(
            company_id=company_id,
            project_id=None,
            q=None,
            limit=limit,
            offset=0,
            sort_by="profit_total",
            sort_dir="asc",
        )
        installer_risk = self.installer_profitability_matrix(
            company_id=company_id,
            limit=limit,
            offset=0,
            sort_by="profit_total",
            sort_dir="asc",
        )
        leakage = self.issues_addons_impact(
            company_id=company_id,
            limit=limit,
        )
        leakage_summary = dict(leakage.get("summary", {}))
        project_items = list(margin_risk.get("items", []))
        order_items = list(order_risk.get("items", []))
        installer_items = list(installer_risk.get("items", []))

        return {
            "summary": {
                "open_issue_profit_at_risk": _dec(
                    leakage_summary.get("open_issue_profit_at_risk")
                ),
                "blocked_issue_profit_at_risk": _dec(
                    leakage_summary.get("blocked_issue_profit_at_risk")
                ),
                "delayed_profit_total": _dec(
                    leakage_summary.get("delayed_profit_total")
                ),
                "risky_projects": len(project_items),
                "risky_orders": len(order_items),
                "risky_installers": len(installer_items),
                "worst_project_profit_total": _dec(
                    project_items[0]["profit_total"] if project_items else 0
                ),
                "worst_order_profit_total": _dec(
                    order_items[0]["profit_total"] if order_items else 0
                ),
                "worst_installer_profit_total": _dec(
                    installer_items[0]["profit_total"] if installer_items else 0
                ),
            },
            "projects": project_items,
            "orders": order_items,
            "installers": installer_items,
        }

    def installer_kpi_details(
        self,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> dict:
        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )
        effective_installer_rate = func.coalesce(
            DoorORM.installer_rate_snapshot,
            InstallerRateORM.price,
            0,
        )

        installed_door_filters = [
            DoorORM.company_id == company_id,
            DoorORM.installer_id == installer_id,
            DoorORM.status == DoorStatus.INSTALLED,
        ]
        all_installer_door_filters = [
            DoorORM.company_id == company_id,
            DoorORM.installer_id == installer_id,
        ]

        summary_row = (
            self.session.query(
                func.count(DoorORM.id).label("installed_doors"),
                func.count(func.distinct(DoorORM.project_id)).label("active_projects"),
                func.count(
                    func.distinct(
                        case(
                            (
                                and_(
                                    DoorORM.order_number.isnot(None),
                                    func.length(func.trim(DoorORM.order_number)) > 0,
                                ),
                                DoorORM.order_number,
                            ),
                            else_=None,
                        )
                    )
                ).label("order_numbers"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label("revenue_total"),
                func.coalesce(func.sum(effective_installer_rate), 0).label("payroll_total"),
                func.coalesce(
                    func.sum(DoorORM.our_price - effective_installer_rate),
                    0,
                ).label("profit_total"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    DoorORM.installer_rate_snapshot.is_(None),
                                    InstallerRateORM.id.is_(None),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing_rates"),
                func.max(DoorORM.installed_at).label("last_installed_at"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(*installed_door_filters)
            .one()
        )

        open_issues = (
            self.session.query(func.count(IssueORM.id))
            .select_from(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.status == IssueStatus.OPEN,
                *all_installer_door_filters,
            )
            .scalar()
        ) or 0

        addon_plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id == ProjectAddonFactORM.addon_type_id,
        )
        addon_row = (
            self.session.query(
                func.coalesce(func.sum(ProjectAddonFactORM.qty_done), 0).label("addons_done_qty"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("addon_revenue_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                    ),
                    0,
                ).label("addon_payroll_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * (
                            func.coalesce(ProjectAddonPlanORM.client_price, 0)
                            - func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                        )
                    ),
                    0,
                ).label("addon_profit_total"),
                func.coalesce(
                    func.sum(case((ProjectAddonPlanORM.id.is_(None), 1), else_=0)),
                    0,
                ).label("missing_addon_plans_facts"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, addon_plan_join)
            .filter(
                ProjectAddonFactORM.company_id == company_id,
                ProjectAddonFactORM.installer_id == installer_id,
            )
            .one()
        )

        project_issue_sub = (
            self.session.query(
                DoorORM.project_id.label("project_id"),
                func.count(IssueORM.id).label("open_issues"),
            )
            .select_from(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.status == IssueStatus.OPEN,
                *all_installer_door_filters,
            )
            .group_by(DoorORM.project_id)
            .subquery()
        )

        project_rows = (
            self.session.query(
                ProjectORM.id.label("project_id"),
                ProjectORM.name.label("project_name"),
                func.count(DoorORM.id).label("installed_doors"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label("revenue_total"),
                func.coalesce(func.sum(effective_installer_rate), 0).label("payroll_total"),
                func.coalesce(
                    func.sum(DoorORM.our_price - effective_installer_rate),
                    0,
                ).label("profit_total"),
                func.coalesce(project_issue_sub.c.open_issues, 0).label("open_issues"),
                func.max(DoorORM.installed_at).label("last_installed_at"),
            )
            .select_from(DoorORM)
            .join(ProjectORM, ProjectORM.id == DoorORM.project_id)
            .outerjoin(InstallerRateORM, rate_join)
            .outerjoin(project_issue_sub, project_issue_sub.c.project_id == DoorORM.project_id)
            .filter(*installed_door_filters)
            .group_by(
                ProjectORM.id,
                ProjectORM.name,
                project_issue_sub.c.open_issues,
            )
            .order_by(
                func.count(DoorORM.id).desc(),
                ProjectORM.name.asc(),
            )
            .limit(5)
            .all()
        )

        order_rows = (
            self.session.query(
                DoorORM.order_number.label("order_number"),
                func.count(DoorORM.id).label("installed_doors"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label("revenue_total"),
                func.coalesce(func.sum(effective_installer_rate), 0).label("payroll_total"),
                func.coalesce(
                    func.sum(DoorORM.our_price - effective_installer_rate),
                    0,
                ).label("profit_total"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(
                *installed_door_filters,
                DoorORM.order_number.isnot(None),
                func.length(func.trim(DoorORM.order_number)) > 0,
            )
            .group_by(DoorORM.order_number)
            .order_by(
                func.count(DoorORM.id).desc(),
                DoorORM.order_number.asc(),
            )
            .limit(8)
            .all()
        )

        door_revenue = _dec(summary_row.revenue_total)
        door_payroll = _dec(summary_row.payroll_total)
        door_profit = _dec(summary_row.profit_total)
        addon_revenue = _dec(addon_row.addon_revenue_total)
        addon_payroll = _dec(addon_row.addon_payroll_total)
        addon_profit = _dec(addon_row.addon_profit_total)

        return {
            "installed_doors": int(summary_row.installed_doors or 0),
            "active_projects": int(summary_row.active_projects or 0),
            "order_numbers": int(summary_row.order_numbers or 0),
            "open_issues": int(open_issues),
            "addons_done_qty": _dec(addon_row.addons_done_qty),
            "addon_revenue_total": addon_revenue,
            "addon_payroll_total": addon_payroll,
            "addon_profit_total": addon_profit,
            "revenue_total": door_revenue + addon_revenue,
            "payroll_total": door_payroll + addon_payroll,
            "profit_total": door_profit + addon_profit,
            "missing_rates_installed_doors": int(summary_row.missing_rates or 0),
            "missing_addon_plans_facts": int(addon_row.missing_addon_plans_facts or 0),
            "last_installed_at": summary_row.last_installed_at,
            "top_projects": [
                {
                    "project_id": row.project_id,
                    "project_name": row.project_name,
                    "installed_doors": int(row.installed_doors or 0),
                    "open_issues": int(row.open_issues or 0),
                    "revenue_total": _dec(row.revenue_total),
                    "payroll_total": _dec(row.payroll_total),
                    "profit_total": _dec(row.profit_total),
                    "last_installed_at": row.last_installed_at,
                }
                for row in project_rows
            ],
            "order_breakdown": [
                {
                    "order_number": str(row.order_number),
                    "installed_doors": int(row.installed_doors or 0),
                    "revenue_total": _dec(row.revenue_total),
                    "payroll_total": _dec(row.payroll_total),
                    "profit_total": _dec(row.profit_total),
                }
                for row in order_rows
            ],
        }

    def order_numbers_kpi(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID | None,
        q: str | None,
        limit: int = 200,
        offset: int = 0,
        sort_by: str = "total_doors",
        sort_dir: str = "desc",
    ) -> dict:
        filters = [
            DoorORM.company_id == company_id,
            DoorORM.order_number.isnot(None),
            func.length(func.trim(DoorORM.order_number)) > 0,
        ]
        if project_id is not None:
            filters.append(DoorORM.project_id == project_id)
        if q:
            filters.append(DoorORM.order_number.ilike(f"%{q.strip()}%"))

        total = int(
            self.session.query(func.count(func.distinct(DoorORM.order_number)))
            .filter(*filters)
            .scalar()
            or 0
        )
        total_doors_expr = func.count(DoorORM.id)
        installed_doors_expr = func.coalesce(
            func.sum(
                case(
                    (DoorORM.status == DoorStatus.INSTALLED, 1),
                    else_=0,
                )
            ),
            0,
        )
        not_installed_doors_expr = func.coalesce(
            func.sum(
                case(
                    (DoorORM.status == DoorStatus.NOT_INSTALLED, 1),
                    else_=0,
                )
            ),
            0,
        )
        planned_revenue_total_expr = func.coalesce(func.sum(DoorORM.our_price), 0)
        installed_revenue_total_expr = func.coalesce(
            func.sum(
                case(
                    (DoorORM.status == DoorStatus.INSTALLED, DoorORM.our_price),
                    else_=0,
                )
            ),
            0,
        )
        payroll_total_expr = func.coalesce(
            func.sum(
                case(
                    (
                        DoorORM.status == DoorStatus.INSTALLED,
                        func.coalesce(DoorORM.installer_rate_snapshot, 0),
                    ),
                    else_=0,
                )
            ),
            0,
        )
        profit_total_expr = func.coalesce(
            func.sum(
                case(
                    (
                        DoorORM.status == DoorStatus.INSTALLED,
                        DoorORM.our_price - func.coalesce(DoorORM.installer_rate_snapshot, 0),
                    ),
                    else_=0,
                )
            ),
            0,
        )
        missing_rates_installed_expr = func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            DoorORM.status == DoorStatus.INSTALLED,
                            DoorORM.installer_rate_snapshot.is_(None),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        )
        sort_map = {
            "order_number": DoorORM.order_number,
            "total_doors": total_doors_expr,
            "installed_doors": installed_doors_expr,
            "not_installed_doors": not_installed_doors_expr,
            "planned_revenue_total": planned_revenue_total_expr,
            "installed_revenue_total": installed_revenue_total_expr,
            "payroll_total": payroll_total_expr,
            "profit_total": profit_total_expr,
            "missing_rates_installed_doors": missing_rates_installed_expr,
        }
        sort_expr = sort_map.get(sort_by, total_doors_expr)
        sort_clause = sort_expr.asc() if sort_dir == "asc" else sort_expr.desc()

        rows = (
            self.session.query(
                DoorORM.order_number.label("order_number"),
                total_doors_expr.label("total_doors"),
                installed_doors_expr.label("installed_doors"),
                not_installed_doors_expr.label("not_installed_doors"),
                planned_revenue_total_expr.label("planned_revenue_total"),
                installed_revenue_total_expr.label("installed_revenue_total"),
                payroll_total_expr.label("payroll_total"),
                profit_total_expr.label("profit_total"),
                missing_rates_installed_expr.label("missing_rates_installed_doors"),
            )
            .filter(*filters)
            .group_by(DoorORM.order_number)
            .order_by(
                sort_clause,
                DoorORM.order_number.asc(),
            )
            .limit(limit)
            .offset(offset)
            .all()
        )

        order_numbers = [str(row.order_number) for row in rows if row.order_number is not None]
        open_issues_by_order: dict[str, int] = {}
        if order_numbers:
            issue_filters = [IssueORM.company_id == company_id, IssueORM.status == IssueStatus.OPEN]
            if project_id is not None:
                issue_filters.append(DoorORM.project_id == project_id)
            issue_rows = (
                self.session.query(
                    DoorORM.order_number.label("order_number"),
                    func.count(IssueORM.id).label("open_issues"),
                )
                .join(
                    DoorORM,
                    and_(
                        DoorORM.company_id == IssueORM.company_id,
                        DoorORM.id == IssueORM.door_id,
                    ),
                )
                .filter(
                    DoorORM.order_number.in_(order_numbers),
                    *issue_filters,
                )
                .group_by(DoorORM.order_number)
                .all()
            )
            open_issues_by_order = {
                str(x.order_number): int(x.open_issues or 0) for x in issue_rows
            }

        items: list[dict] = []
        for row in rows:
            order_number = str(row.order_number)
            total_doors = int(row.total_doors or 0)
            installed_doors = int(row.installed_doors or 0)
            completion_pct = (
                round((installed_doors / total_doors) * 100.0, 2)
                if total_doors > 0
                else 0.0
            )
            items.append(
                {
                    "order_number": order_number,
                    "total_doors": total_doors,
                    "installed_doors": installed_doors,
                    "not_installed_doors": int(row.not_installed_doors or 0),
                    "open_issues": int(open_issues_by_order.get(order_number, 0)),
                    "planned_revenue_total": _dec(row.planned_revenue_total),
                    "installed_revenue_total": _dec(row.installed_revenue_total),
                    "payroll_total": _dec(row.payroll_total),
                    "profit_total": _dec(row.profit_total),
                    "missing_rates_installed_doors": int(
                        row.missing_rates_installed_doors or 0
                    ),
                    "completion_pct": completion_pct,
                }
            )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }

    def project_profit(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> dict:
        installed_filter = [
            DoorORM.status == DoorStatus.INSTALLED,
            DoorORM.project_id == project_id,
        ]
        if date_from is not None:
            installed_filter.append(DoorORM.installed_at >= date_from)
        if date_to is not None:
            installed_filter.append(DoorORM.installed_at < date_to)

        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )
        effective_installer_rate = func.coalesce(
            DoorORM.installer_rate_snapshot,
            InstallerRateORM.price,
            0,
        )

        row = (
            self.session.query(
                func.count(DoorORM.id).label("installed_doors"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label("revenue"),
                func.coalesce(func.sum(effective_installer_rate), 0).label("payroll"),
                func.coalesce(
                    func.sum(
                        DoorORM.our_price - effective_installer_rate
                    ),
                    0,
                ).label("profit"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    DoorORM.installer_rate_snapshot.is_(None),
                                    InstallerRateORM.id.is_(None),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing_rates"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(DoorORM.company_id == company_id, *installed_filter)
            .one()
        )

        door_revenue = _dec(row.revenue)
        door_payroll = _dec(row.payroll)
        door_profit = _dec(row.profit)

        addon_filter = [
            ProjectAddonFactORM.company_id == company_id,
            ProjectAddonFactORM.project_id == project_id,
        ]
        if date_from is not None:
            addon_filter.append(ProjectAddonFactORM.done_at >= date_from)
        if date_to is not None:
            addon_filter.append(ProjectAddonFactORM.done_at < date_to)

        plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id == ProjectAddonFactORM.addon_type_id,
        )

        addon_row = (
            self.session.query(
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("addon_revenue"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                    ),
                    0,
                ).label("addon_payroll"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * (
                            func.coalesce(ProjectAddonPlanORM.client_price, 0)
                            - func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                        )
                    ),
                    0,
                ).label("addon_profit"),
                func.coalesce(
                    func.sum(
                        case(
                            (ProjectAddonPlanORM.id.is_(None), 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("addon_missing_plan"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, plan_join)
            .filter(*addon_filter)
            .one()
        )

        revenue_total = door_revenue + _dec(addon_row.addon_revenue)
        payroll_total = door_payroll + _dec(addon_row.addon_payroll)
        profit_total = door_profit + _dec(addon_row.addon_profit)

        return {
            "installed_doors": int(row.installed_doors or 0),
            "revenue_total": revenue_total,
            "payroll_total": payroll_total,
            "profit_total": profit_total,
            "missing_rates_installed_doors": int(row.missing_rates or 0),
        }

    def project_plan_fact(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> dict:
        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )
        effective_installer_rate = func.coalesce(
            DoorORM.installer_rate_snapshot,
            InstallerRateORM.price,
            0,
        )

        door_row = (
            self.session.query(
                func.count(DoorORM.id).label("total_doors"),
                func.coalesce(
                    func.sum(
                        case((DoorORM.status == DoorStatus.INSTALLED, 1), else_=0)
                    ),
                    0,
                ).label("installed_doors"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label("planned_revenue"),
                func.coalesce(func.sum(effective_installer_rate), 0).label("planned_payroll"),
                func.coalesce(
                    func.sum(DoorORM.our_price - effective_installer_rate),
                    0,
                ).label("planned_profit"),
                func.coalesce(
                    func.sum(
                        case(
                            (DoorORM.status == DoorStatus.INSTALLED, DoorORM.our_price),
                            else_=0,
                        )
                    ),
                    0,
                ).label("actual_revenue"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                DoorORM.status == DoorStatus.INSTALLED,
                                effective_installer_rate,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("actual_payroll"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                DoorORM.status == DoorStatus.INSTALLED,
                                DoorORM.our_price - effective_installer_rate,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("actual_profit"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    DoorORM.installer_rate_snapshot.is_(None),
                                    InstallerRateORM.id.is_(None),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing_planned_rates"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    DoorORM.status == DoorStatus.INSTALLED,
                                    DoorORM.installer_rate_snapshot.is_(None),
                                    InstallerRateORM.id.is_(None),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing_actual_rates"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.project_id == project_id,
            )
            .one()
        )

        plan_row = (
            self.session.query(
                func.coalesce(func.sum(ProjectAddonPlanORM.qty_planned), 0).label(
                    "planned_qty"
                ),
                func.coalesce(
                    func.sum(
                        ProjectAddonPlanORM.qty_planned
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("planned_revenue"),
                func.coalesce(
                    func.sum(
                        ProjectAddonPlanORM.qty_planned
                        * func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                    ),
                    0,
                ).label("planned_payroll"),
                func.coalesce(
                    func.sum(
                        ProjectAddonPlanORM.qty_planned
                        * (
                            func.coalesce(ProjectAddonPlanORM.client_price, 0)
                            - func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                        )
                    ),
                    0,
                ).label("planned_profit"),
            )
            .select_from(ProjectAddonPlanORM)
            .filter(
                ProjectAddonPlanORM.company_id == company_id,
                ProjectAddonPlanORM.project_id == project_id,
            )
            .one()
        )

        addon_plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id == ProjectAddonFactORM.addon_type_id,
        )
        fact_row = (
            self.session.query(
                func.coalesce(func.sum(ProjectAddonFactORM.qty_done), 0).label("actual_qty"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("actual_revenue"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                    ),
                    0,
                ).label("actual_payroll"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * (
                            func.coalesce(ProjectAddonPlanORM.client_price, 0)
                            - func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                        )
                    ),
                    0,
                ).label("actual_profit"),
                func.coalesce(
                    func.sum(case((ProjectAddonPlanORM.id.is_(None), 1), else_=0)),
                    0,
                ).label("missing_addon_plans_facts"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, addon_plan_join)
            .filter(
                ProjectAddonFactORM.company_id == company_id,
                ProjectAddonFactORM.project_id == project_id,
            )
            .one()
        )

        open_issues = (
            self.session.query(func.count(IssueORM.id))
            .select_from(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                DoorORM.project_id == project_id,
                IssueORM.status == IssueStatus.OPEN,
            )
            .scalar()
        ) or 0

        total_doors = int(door_row.total_doors or 0)
        installed_doors = int(door_row.installed_doors or 0)
        not_installed_doors = max(total_doors - installed_doors, 0)
        completion_pct = round((installed_doors / total_doors) * 100, 2) if total_doors else 0.0

        planned_revenue_total = _dec(door_row.planned_revenue) + _dec(plan_row.planned_revenue)
        actual_revenue_total = _dec(door_row.actual_revenue) + _dec(fact_row.actual_revenue)
        planned_payroll_total = _dec(door_row.planned_payroll) + _dec(plan_row.planned_payroll)
        actual_payroll_total = _dec(door_row.actual_payroll) + _dec(fact_row.actual_payroll)
        planned_profit_total = _dec(door_row.planned_profit) + _dec(plan_row.planned_profit)
        actual_profit_total = _dec(door_row.actual_profit) + _dec(fact_row.actual_profit)

        return {
            "total_doors": total_doors,
            "installed_doors": installed_doors,
            "not_installed_doors": not_installed_doors,
            "completion_pct": completion_pct,
            "open_issues": int(open_issues),
            "planned_revenue_total": planned_revenue_total,
            "actual_revenue_total": actual_revenue_total,
            "revenue_gap_total": planned_revenue_total - actual_revenue_total,
            "planned_payroll_total": planned_payroll_total,
            "actual_payroll_total": actual_payroll_total,
            "payroll_gap_total": planned_payroll_total - actual_payroll_total,
            "planned_profit_total": planned_profit_total,
            "actual_profit_total": actual_profit_total,
            "profit_gap_total": planned_profit_total - actual_profit_total,
            "planned_addons_qty": _dec(plan_row.planned_qty),
            "actual_addons_qty": _dec(fact_row.actual_qty),
            "missing_planned_rates_doors": int(door_row.missing_planned_rates or 0),
            "missing_actual_rates_doors": int(door_row.missing_actual_rates or 0),
            "missing_addon_plans_facts": int(fact_row.missing_addon_plans_facts or 0),
        }

    def project_risk_drilldown(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        limit: int = 5,
    ) -> dict:
        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )
        effective_installer_rate = func.coalesce(
            DoorORM.installer_rate_snapshot,
            InstallerRateORM.price,
            0,
        )

        plan_fact = self.project_plan_fact(
            company_id=company_id,
            project_id=project_id,
        )

        blocked_open_issues = int(
            self.session.query(func.count(IssueORM.id))
            .select_from(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                DoorORM.project_id == project_id,
                IssueORM.status == IssueStatus.OPEN,
                IssueORM.workflow_state == IssueWorkflowState.BLOCKED,
            )
            .scalar()
            or 0
        )

        blocked_issue_profit_at_risk = _dec(
            self.session.query(
                func.coalesce(
                    func.sum(DoorORM.our_price - effective_installer_rate),
                    0,
                )
            )
            .select_from(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(
                IssueORM.company_id == company_id,
                DoorORM.project_id == project_id,
                IssueORM.status == IssueStatus.OPEN,
                IssueORM.workflow_state == IssueWorkflowState.BLOCKED,
            )
            .scalar()
        )

        delayed_row = (
            self.session.query(
                func.coalesce(func.sum(DoorORM.our_price), 0).label("delayed_revenue_total"),
                func.coalesce(
                    func.sum(DoorORM.our_price - effective_installer_rate),
                    0,
                ).label("delayed_profit_total"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.project_id == project_id,
                DoorORM.status == DoorStatus.NOT_INSTALLED,
            )
            .one()
        )

        addon_plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id == ProjectAddonFactORM.addon_type_id,
        )
        addon_row = (
            self.session.query(
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("addon_revenue_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * (
                            func.coalesce(ProjectAddonPlanORM.client_price, 0)
                            - func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                        )
                    ),
                    0,
                ).label("addon_profit_total"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, addon_plan_join)
            .filter(
                ProjectAddonFactORM.company_id == company_id,
                ProjectAddonFactORM.project_id == project_id,
            )
            .one()
        )

        reason_profit_expr = func.coalesce(
            func.sum(DoorORM.our_price - effective_installer_rate),
            0,
        )
        reason_name_expr = func.coalesce(ReasonORM.name, "No reason")
        reason_rows = (
            self.session.query(
                DoorORM.reason_id.label("reason_id"),
                reason_name_expr.label("reason_name"),
                func.count(DoorORM.id).label("doors"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label("revenue_delayed_total"),
                reason_profit_expr.label("profit_delayed_total"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .outerjoin(
                ReasonORM,
                and_(
                    ReasonORM.company_id == DoorORM.company_id,
                    ReasonORM.id == DoorORM.reason_id,
                ),
            )
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.project_id == project_id,
                DoorORM.status == DoorStatus.NOT_INSTALLED,
            )
            .group_by(DoorORM.reason_id, reason_name_expr)
            .order_by(reason_profit_expr.desc(), func.count(DoorORM.id).desc())
            .limit(limit)
            .all()
        )

        order_total_doors_expr = func.count(DoorORM.id)
        order_installed_doors_expr = func.coalesce(
            func.sum(case((DoorORM.status == DoorStatus.INSTALLED, 1), else_=0)),
            0,
        )
        order_actual_revenue_expr = func.coalesce(
            func.sum(
                case((DoorORM.status == DoorStatus.INSTALLED, DoorORM.our_price), else_=0)
            ),
            0,
        )
        order_actual_profit_expr = func.coalesce(
            func.sum(
                case(
                    (
                        DoorORM.status == DoorStatus.INSTALLED,
                        DoorORM.our_price - effective_installer_rate,
                    ),
                    else_=0,
                )
            ),
            0,
        )
        order_issue_sub = (
            self.session.query(
                DoorORM.order_number.label("order_number"),
                func.count(IssueORM.id).label("open_issues"),
            )
            .select_from(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                DoorORM.project_id == project_id,
                IssueORM.status == IssueStatus.OPEN,
                DoorORM.order_number.isnot(None),
                func.length(func.trim(DoorORM.order_number)) > 0,
            )
            .group_by(DoorORM.order_number)
            .subquery()
        )
        order_rows = (
            self.session.query(
                DoorORM.order_number.label("order_number"),
                order_total_doors_expr.label("total_doors"),
                order_installed_doors_expr.label("installed_doors"),
                func.coalesce(order_issue_sub.c.open_issues, 0).label("open_issues"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label("planned_revenue_total"),
                order_actual_revenue_expr.label("actual_revenue_total"),
                order_actual_profit_expr.label("actual_profit_total"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .outerjoin(order_issue_sub, order_issue_sub.c.order_number == DoorORM.order_number)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.project_id == project_id,
                DoorORM.order_number.isnot(None),
                func.length(func.trim(DoorORM.order_number)) > 0,
            )
            .group_by(
                DoorORM.order_number,
                order_issue_sub.c.open_issues,
            )
            .order_by(
                (
                    func.coalesce(func.sum(DoorORM.our_price), 0)
                    - order_actual_revenue_expr
                ).desc(),
                func.coalesce(order_issue_sub.c.open_issues, 0).desc(),
                DoorORM.order_number.asc(),
            )
            .limit(limit)
            .all()
        )

        actual_margin_pct = (
            round(
                (
                    float(plan_fact["actual_profit_total"])
                    / float(plan_fact["actual_revenue_total"])
                    * 100.0
                ),
                2,
            )
            if float(plan_fact["actual_revenue_total"]) > 0
            else 0.0
        )

        return {
            "summary": {
                **plan_fact,
                "blocked_open_issues": blocked_open_issues,
                "actual_margin_pct": actual_margin_pct,
                "delayed_revenue_total": _dec(delayed_row.delayed_revenue_total),
                "delayed_profit_total": _dec(delayed_row.delayed_profit_total),
                "blocked_issue_profit_at_risk": blocked_issue_profit_at_risk,
                "addon_revenue_total": _dec(addon_row.addon_revenue_total),
                "addon_profit_total": _dec(addon_row.addon_profit_total),
            },
            "top_reasons": [
                {
                    "reason_id": row.reason_id,
                    "reason_name": row.reason_name,
                    "doors": int(row.doors or 0),
                    "revenue_delayed_total": _dec(row.revenue_delayed_total),
                    "profit_delayed_total": _dec(row.profit_delayed_total),
                }
                for row in reason_rows
            ],
            "risky_orders": [
                {
                    "order_number": str(row.order_number),
                    "total_doors": int(row.total_doors or 0),
                    "installed_doors": int(row.installed_doors or 0),
                    "not_installed_doors": max(
                        int(row.total_doors or 0) - int(row.installed_doors or 0),
                        0,
                    ),
                    "open_issues": int(row.open_issues or 0),
                    "planned_revenue_total": _dec(row.planned_revenue_total),
                    "actual_revenue_total": _dec(row.actual_revenue_total),
                    "revenue_gap_total": _dec(row.planned_revenue_total)
                    - _dec(row.actual_revenue_total),
                    "actual_profit_total": _dec(row.actual_profit_total),
                    "completion_pct": round(
                        (int(row.installed_doors or 0) / int(row.total_doors or 1)) * 100.0,
                        2,
                    )
                    if int(row.total_doors or 0) > 0
                    else 0.0,
                }
                for row in order_rows
            ],
        }

    def projects_margin(
        self,
        *,
        company_id: uuid.UUID,
        limit: int = 10,
        offset: int = 0,
        sort_by: str = "profit_total",
        sort_dir: str = "desc",
    ) -> dict:
        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )
        effective_installer_rate = func.coalesce(
            DoorORM.installer_rate_snapshot,
            InstallerRateORM.price,
            0,
        )

        door_sub = (
            self.session.query(
                DoorORM.project_id.label("project_id"),
                func.count(DoorORM.id).label("total_doors"),
                func.coalesce(
                    func.sum(case((DoorORM.status == DoorStatus.INSTALLED, 1), else_=0)),
                    0,
                ).label("installed_doors"),
                func.coalesce(
                    func.sum(
                        case((DoorORM.status == DoorStatus.INSTALLED, DoorORM.our_price), else_=0)
                    ),
                    0,
                ).label("revenue_total"),
                func.coalesce(
                    func.sum(
                        case(
                            (DoorORM.status == DoorStatus.INSTALLED, effective_installer_rate),
                            else_=0,
                        )
                    ),
                    0,
                ).label("payroll_total"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                DoorORM.status == DoorStatus.INSTALLED,
                                DoorORM.our_price - effective_installer_rate,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("profit_total"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    DoorORM.status == DoorStatus.INSTALLED,
                                    DoorORM.installer_rate_snapshot.is_(None),
                                    InstallerRateORM.id.is_(None),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing_rates_installed_doors"),
                func.max(DoorORM.installed_at).label("last_installed_at"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(DoorORM.company_id == company_id)
            .group_by(DoorORM.project_id)
            .subquery()
        )

        issue_sub = (
            self.session.query(
                DoorORM.project_id.label("project_id"),
                func.count(IssueORM.id).label("open_issues"),
            )
            .select_from(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.status == IssueStatus.OPEN,
            )
            .group_by(DoorORM.project_id)
            .subquery()
        )

        addon_plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id == ProjectAddonFactORM.addon_type_id,
        )
        addon_sub = (
            self.session.query(
                ProjectAddonFactORM.project_id.label("project_id"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("addon_revenue_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                    ),
                    0,
                ).label("addon_payroll_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * (
                            func.coalesce(ProjectAddonPlanORM.client_price, 0)
                            - func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                        )
                    ),
                    0,
                ).label("addon_profit_total"),
                func.coalesce(
                    func.sum(case((ProjectAddonPlanORM.id.is_(None), 1), else_=0)),
                    0,
                ).label("missing_addon_plans_facts"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, addon_plan_join)
            .filter(ProjectAddonFactORM.company_id == company_id)
            .group_by(ProjectAddonFactORM.project_id)
            .subquery()
        )

        total = int(
            self.session.query(func.count(ProjectORM.id))
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.deleted_at.is_(None),
            )
            .scalar()
            or 0
        )

        revenue_expr = func.coalesce(door_sub.c.revenue_total, 0) + func.coalesce(
            addon_sub.c.addon_revenue_total, 0
        )
        payroll_expr = func.coalesce(door_sub.c.payroll_total, 0) + func.coalesce(
            addon_sub.c.addon_payroll_total, 0
        )
        profit_expr = func.coalesce(door_sub.c.profit_total, 0) + func.coalesce(
            addon_sub.c.addon_profit_total, 0
        )
        completion_expr = case(
            (
                func.coalesce(door_sub.c.total_doors, 0) > 0,
                (
                    func.coalesce(door_sub.c.installed_doors, 0) * 100.0
                    / func.coalesce(door_sub.c.total_doors, 1)
                ),
            ),
            else_=0.0,
        )
        margin_expr = case(
            (revenue_expr > 0, (profit_expr * 100.0 / revenue_expr)),
            else_=0.0,
        )
        open_issues_expr = func.coalesce(issue_sub.c.open_issues, 0)
        sort_map = {
            "profit_total": profit_expr,
            "margin_pct": margin_expr,
            "completion_pct": completion_expr,
            "open_issues": open_issues_expr,
        }
        sort_expr = sort_map.get(sort_by, profit_expr)
        sort_clause = sort_expr.asc() if sort_dir == "asc" else sort_expr.desc()

        rows = (
            self.session.query(
                ProjectORM.id.label("project_id"),
                ProjectORM.name.label("project_name"),
                ProjectORM.status.label("project_status"),
                func.coalesce(door_sub.c.total_doors, 0).label("total_doors"),
                func.coalesce(door_sub.c.installed_doors, 0).label("installed_doors"),
                completion_expr.label("completion_pct"),
                open_issues_expr.label("open_issues"),
                revenue_expr.label("revenue_total"),
                payroll_expr.label("payroll_total"),
                profit_expr.label("profit_total"),
                margin_expr.label("margin_pct"),
                func.coalesce(
                    door_sub.c.missing_rates_installed_doors,
                    0,
                ).label("missing_rates_installed_doors"),
                func.coalesce(
                    addon_sub.c.missing_addon_plans_facts,
                    0,
                ).label("missing_addon_plans_facts"),
                door_sub.c.last_installed_at.label("last_installed_at"),
            )
            .select_from(ProjectORM)
            .outerjoin(door_sub, door_sub.c.project_id == ProjectORM.id)
            .outerjoin(issue_sub, issue_sub.c.project_id == ProjectORM.id)
            .outerjoin(addon_sub, addon_sub.c.project_id == ProjectORM.id)
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.deleted_at.is_(None),
            )
            .order_by(sort_clause, ProjectORM.name.asc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        return {
            "total": total,
            "items": [
                {
                    "project_id": row.project_id,
                    "project_name": row.project_name,
                    "project_status": (
                        row.project_status.value
                        if hasattr(row.project_status, "value")
                        else str(row.project_status)
                    ),
                    "total_doors": int(row.total_doors or 0),
                    "installed_doors": int(row.installed_doors or 0),
                    "completion_pct": round(float(row.completion_pct or 0), 2),
                    "open_issues": int(row.open_issues or 0),
                    "revenue_total": _dec(row.revenue_total),
                    "payroll_total": _dec(row.payroll_total),
                    "profit_total": _dec(row.profit_total),
                    "margin_pct": round(float(row.margin_pct or 0), 2),
                    "missing_rates_installed_doors": int(
                        row.missing_rates_installed_doors or 0
                    ),
                    "missing_addon_plans_facts": int(
                        row.missing_addon_plans_facts or 0
                    ),
                    "last_installed_at": row.last_installed_at,
                }
                for row in rows
            ],
        }

    def issues_addons_impact(
        self,
        *,
        company_id: uuid.UUID,
        limit: int = 10,
    ) -> dict:
        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )
        effective_installer_rate = func.coalesce(
            DoorORM.installer_rate_snapshot,
            InstallerRateORM.price,
            0,
        )

        open_issue_row = (
            self.session.query(
                func.count(IssueORM.id).label("open_issues"),
                func.coalesce(
                    func.sum(
                        case(
                            (IssueORM.workflow_state == IssueWorkflowState.BLOCKED, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("blocked_open_issues"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label(
                    "open_issue_revenue_at_risk"
                ),
                func.coalesce(func.sum(effective_installer_rate), 0).label(
                    "open_issue_payroll_at_risk"
                ),
                func.coalesce(
                    func.sum(DoorORM.our_price - effective_installer_rate),
                    0,
                ).label("open_issue_profit_at_risk"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                IssueORM.workflow_state == IssueWorkflowState.BLOCKED,
                                DoorORM.our_price - effective_installer_rate,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("blocked_issue_profit_at_risk"),
            )
            .select_from(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.status == IssueStatus.OPEN,
            )
            .one()
        )

        not_installed_row = (
            self.session.query(
                func.count(DoorORM.id).label("not_installed_doors"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label(
                    "delayed_revenue_total"
                ),
                func.coalesce(func.sum(effective_installer_rate), 0).label(
                    "delayed_payroll_total"
                ),
                func.coalesce(
                    func.sum(DoorORM.our_price - effective_installer_rate),
                    0,
                ).label("delayed_profit_total"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.status == DoorStatus.NOT_INSTALLED,
            )
            .one()
        )

        reason_name_expr = func.coalesce(ReasonORM.name, "No reason")
        reason_profit_expr = func.coalesce(
            func.sum(DoorORM.our_price - effective_installer_rate),
            0,
        )
        reason_rows = (
            self.session.query(
                DoorORM.reason_id.label("reason_id"),
                reason_name_expr.label("reason_name"),
                func.count(DoorORM.id).label("doors"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label(
                    "revenue_delayed_total"
                ),
                func.coalesce(func.sum(effective_installer_rate), 0).label(
                    "payroll_delayed_total"
                ),
                reason_profit_expr.label("profit_delayed_total"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .outerjoin(
                ReasonORM,
                and_(
                    ReasonORM.company_id == DoorORM.company_id,
                    ReasonORM.id == DoorORM.reason_id,
                ),
            )
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.status == DoorStatus.NOT_INSTALLED,
            )
            .group_by(DoorORM.reason_id, reason_name_expr)
            .order_by(reason_profit_expr.desc(), func.count(DoorORM.id).desc())
            .limit(limit)
            .all()
        )

        addon_plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id == ProjectAddonFactORM.addon_type_id,
        )
        addon_name_expr = func.coalesce(AddonTypeORM.name, "Unknown add-on")
        addon_profit_expr = func.coalesce(
            func.sum(
                ProjectAddonFactORM.qty_done
                * (
                    func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    - func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                )
            ),
            0,
        )
        addon_summary_row = (
            self.session.query(
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("addon_revenue_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                    ),
                    0,
                ).label("addon_payroll_total"),
                addon_profit_expr.label("addon_profit_total"),
                func.coalesce(
                    func.sum(case((ProjectAddonPlanORM.id.is_(None), 1), else_=0)),
                    0,
                ).label("missing_addon_plans_facts"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, addon_plan_join)
            .filter(ProjectAddonFactORM.company_id == company_id)
            .one()
        )
        addon_rows = (
            self.session.query(
                ProjectAddonFactORM.addon_type_id.label("addon_type_id"),
                addon_name_expr.label("addon_name"),
                func.coalesce(func.sum(ProjectAddonFactORM.qty_done), 0).label("qty_done"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.client_price, 0)
                    ),
                    0,
                ).label("revenue_total"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(ProjectAddonPlanORM.installer_price, 0)
                    ),
                    0,
                ).label("payroll_total"),
                addon_profit_expr.label("profit_total"),
                func.coalesce(
                    func.sum(case((ProjectAddonPlanORM.id.is_(None), 1), else_=0)),
                    0,
                ).label("missing_plan_facts"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, addon_plan_join)
            .outerjoin(
                AddonTypeORM,
                and_(
                    AddonTypeORM.company_id == ProjectAddonFactORM.company_id,
                    AddonTypeORM.id == ProjectAddonFactORM.addon_type_id,
                ),
            )
            .filter(ProjectAddonFactORM.company_id == company_id)
            .group_by(ProjectAddonFactORM.addon_type_id, addon_name_expr)
            .order_by(addon_profit_expr.desc(), func.sum(ProjectAddonFactORM.qty_done).desc())
            .limit(limit)
            .all()
        )

        return {
            "summary": {
                "open_issues": int(open_issue_row.open_issues or 0),
                "blocked_open_issues": int(open_issue_row.blocked_open_issues or 0),
                "not_installed_doors": int(not_installed_row.not_installed_doors or 0),
                "open_issue_revenue_at_risk": _dec(
                    open_issue_row.open_issue_revenue_at_risk
                ),
                "open_issue_payroll_at_risk": _dec(
                    open_issue_row.open_issue_payroll_at_risk
                ),
                "open_issue_profit_at_risk": _dec(
                    open_issue_row.open_issue_profit_at_risk
                ),
                "blocked_issue_profit_at_risk": _dec(
                    open_issue_row.blocked_issue_profit_at_risk
                ),
                "delayed_revenue_total": _dec(not_installed_row.delayed_revenue_total),
                "delayed_payroll_total": _dec(not_installed_row.delayed_payroll_total),
                "delayed_profit_total": _dec(not_installed_row.delayed_profit_total),
                "addon_revenue_total": _dec(addon_summary_row.addon_revenue_total),
                "addon_payroll_total": _dec(addon_summary_row.addon_payroll_total),
                "addon_profit_total": _dec(addon_summary_row.addon_profit_total),
                "missing_addon_plans_facts": int(
                    addon_summary_row.missing_addon_plans_facts or 0
                ),
            },
            "top_reasons": [
                {
                    "reason_id": row.reason_id,
                    "reason_name": row.reason_name,
                    "doors": int(row.doors or 0),
                    "revenue_delayed_total": _dec(row.revenue_delayed_total),
                    "payroll_delayed_total": _dec(row.payroll_delayed_total),
                    "profit_delayed_total": _dec(row.profit_delayed_total),
                }
                for row in reason_rows
            ],
            "addon_impact": [
                {
                    "addon_type_id": row.addon_type_id,
                    "addon_name": row.addon_name,
                    "qty_done": _dec(row.qty_done),
                    "revenue_total": _dec(row.revenue_total),
                    "payroll_total": _dec(row.payroll_total),
                    "profit_total": _dec(row.profit_total),
                    "missing_plan_facts": int(row.missing_plan_facts or 0),
                }
                for row in addon_rows
            ],
        }

    def delivery_stats(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> dict:
        q = self.session.query(OutboxMessageORM).filter(
            OutboxMessageORM.company_id == company_id
        )
        if date_from is not None:
            q = q.filter(OutboxMessageORM.created_at >= date_from)
        if date_to is not None:
            q = q.filter(OutboxMessageORM.created_at < date_to)

        wa = q.filter(OutboxMessageORM.channel == OutboxChannel.WHATSAPP)
        whatsapp_pending = wa.filter(
            OutboxMessageORM.delivery_status == DeliveryStatus.PENDING
        ).count()
        whatsapp_delivered = wa.filter(
            OutboxMessageORM.delivery_status == DeliveryStatus.DELIVERED
        ).count()
        whatsapp_failed = wa.filter(
            OutboxMessageORM.delivery_status == DeliveryStatus.FAILED
        ).count()

        em = q.filter(OutboxMessageORM.channel == OutboxChannel.EMAIL)
        email_sent = em.filter(OutboxMessageORM.status == OutboxStatus.SENT).count()
        email_failed = em.filter(OutboxMessageORM.status == OutboxStatus.FAILED).count()

        return {
            "whatsapp_pending": whatsapp_pending,
            "whatsapp_delivered": whatsapp_delivered,
            "whatsapp_failed": whatsapp_failed,
            "email_sent": email_sent,
            "email_failed": email_failed,
        }

    def audit_catalog_changes(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        entity_type: str | None,
        action: str | None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        q = self._audit_catalog_query(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            entity_type=entity_type,
            action=action,
        )

        total = q.count()
        by_entity_rows = (
            q.with_entities(
                AuditLogORM.entity_type,
                func.count(AuditLogORM.id),
            )
            .group_by(AuditLogORM.entity_type)
            .all()
        )
        by_action_rows = (
            q.with_entities(
                AuditLogORM.action,
                func.count(AuditLogORM.id),
            )
            .group_by(AuditLogORM.action)
            .all()
        )

        rows = (
            q.order_by(AuditLogORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        by_entity = {key: int(value) for key, value in by_entity_rows}
        by_action = {key: int(value) for key, value in by_action_rows}

        return {
            "items": [
                {
                    "id": r.id,
                    "created_at": r.created_at,
                    "actor_user_id": r.actor_user_id,
                    "entity_type": r.entity_type,
                    "entity_id": r.entity_id,
                    "action": r.action,
                    "reason": r.reason,
                    "before": r.before,
                    "after": r.after,
                }
                for r in rows
            ],
            "summary": {
                "total": int(total),
                "by_entity": by_entity,
                "by_action": by_action,
            },
        }

    def audit_catalog_changes_export_rows(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        entity_type: str | None,
        action: str | None,
        limit: int = 5000,
    ) -> list[dict]:
        q = self._audit_catalog_query(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            entity_type=entity_type,
            action=action,
        )
        rows = q.order_by(AuditLogORM.created_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "created_at": r.created_at,
                "actor_user_id": r.actor_user_id,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "action": r.action,
                "reason": r.reason,
                "before": r.before,
                "after": r.after,
            }
            for r in rows
        ]

    def audit_issue_changes(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        issue_id: uuid.UUID | None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        q = self._audit_issue_query(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            issue_id=issue_id,
        )

        total = q.count()
        by_action_rows = (
            q.with_entities(
                AuditLogORM.action,
                func.count(AuditLogORM.id),
            )
            .group_by(AuditLogORM.action)
            .all()
        )
        rows = (
            q.order_by(AuditLogORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        by_action = {key: int(value) for key, value in by_action_rows}

        return {
            "items": [
                {
                    "id": r.id,
                    "created_at": r.created_at,
                    "actor_user_id": r.actor_user_id,
                    "entity_type": r.entity_type,
                    "entity_id": r.entity_id,
                    "action": r.action,
                    "reason": r.reason,
                    "before": r.before,
                    "after": r.after,
                }
                for r in rows
            ],
            "summary": {
                "total": int(total),
                "by_entity": {"issue": int(total)},
                "by_action": by_action,
            },
        }

    def audit_issue_changes_export_rows(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        issue_id: uuid.UUID | None,
        limit: int = 5000,
    ) -> list[dict]:
        q = self._audit_issue_query(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            issue_id=issue_id,
        )
        rows = q.order_by(AuditLogORM.created_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "created_at": r.created_at,
                "actor_user_id": r.actor_user_id,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "action": r.action,
                "reason": r.reason,
                "before": r.before,
                "after": r.after,
            }
            for r in rows
        ]

    def audit_installer_rate_changes(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        rate_id: uuid.UUID | None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        q = self._audit_installer_rate_query(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            rate_id=rate_id,
        )

        total = q.count()
        by_action_rows = (
            q.with_entities(
                AuditLogORM.action,
                func.count(AuditLogORM.id),
            )
            .group_by(AuditLogORM.action)
            .all()
        )
        rows = (
            q.order_by(AuditLogORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        by_action = {key: int(value) for key, value in by_action_rows}

        return {
            "items": [
                {
                    "id": r.id,
                    "created_at": r.created_at,
                    "actor_user_id": r.actor_user_id,
                    "entity_type": r.entity_type,
                    "entity_id": r.entity_id,
                    "action": r.action,
                    "reason": r.reason,
                    "before": r.before,
                    "after": r.after,
                }
                for r in rows
            ],
            "summary": {
                "total": int(total),
                "by_entity": {"installer_rate": int(total)},
                "by_action": by_action,
            },
        }

    def audit_installer_rate_changes_export_rows(
        self,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        rate_id: uuid.UUID | None,
        limit: int = 5000,
    ) -> list[dict]:
        q = self._audit_installer_rate_query(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            rate_id=rate_id,
        )
        rows = q.order_by(AuditLogORM.created_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "created_at": r.created_at,
                "actor_user_id": r.actor_user_id,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "action": r.action,
                "reason": r.reason,
                "before": r.before,
                "after": r.after,
            }
            for r in rows
        ]

    def operations_center(
        self,
        *,
        company_id: uuid.UUID,
        now: datetime,
    ) -> dict:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        imports_window_hours = 24
        failing_projects_window_hours = 168

        imports_since = now - timedelta(hours=imports_window_hours)
        recent_import_runs = (
            self.session.query(ProjectImportRunORM)
            .filter(
                ProjectImportRunORM.company_id == company_id,
                ProjectImportRunORM.created_at >= imports_since,
            )
            .order_by(ProjectImportRunORM.created_at.desc())
            .all()
        )

        imports = {
            "window_hours": imports_window_hours,
            "total_runs": len(recent_import_runs),
            "analyze_runs": 0,
            "import_runs": 0,
            "retry_runs": 0,
            "success_runs": 0,
            "partial_runs": 0,
            "failed_runs": 0,
            "empty_runs": 0,
        }
        for run in recent_import_runs:
            mode = str(run.import_mode or "")
            if mode == "analyze":
                imports["analyze_runs"] += 1
            elif mode == "import":
                imports["import_runs"] += 1
            elif mode == "import_retry":
                imports["retry_runs"] += 1

            status = _import_run_status(run)
            if status == "SUCCESS":
                imports["success_runs"] += 1
            elif status == "PARTIAL":
                imports["partial_runs"] += 1
            elif status == "FAILED":
                imports["failed_runs"] += 1
            elif status == "EMPTY":
                imports["empty_runs"] += 1

        outbox_base = self.session.query(OutboxMessageORM).filter(
            OutboxMessageORM.company_id == company_id
        )
        outbox_by_channel_rows = (
            outbox_base.with_entities(
                OutboxMessageORM.channel,
                func.count(OutboxMessageORM.id),
            )
            .group_by(OutboxMessageORM.channel)
            .all()
        )
        outbox = {
            "total": int(outbox_base.count()),
            "failed_total": int(
                outbox_base.filter(OutboxMessageORM.status == OutboxStatus.FAILED).count()
            ),
            "pending_overdue_15m": int(
                outbox_base.filter(
                    OutboxMessageORM.status == OutboxStatus.PENDING,
                    OutboxMessageORM.scheduled_at < (now - timedelta(minutes=15)),
                ).count()
            ),
            "by_channel": {
                (channel.value if hasattr(channel, "value") else str(channel)): int(count)
                for channel, count in outbox_by_channel_rows
            },
        }

        alerts_base = self.session.query(AuditLogORM).filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.action.like("PLAN_LIMIT_ALERT_%"),
        )
        alerts_since = now - timedelta(hours=24)
        alerts_24h = alerts_base.filter(AuditLogORM.created_at >= alerts_since)
        alerts = {
            "total_last_24h": int(alerts_24h.count()),
            "warn_last_24h": int(
                alerts_24h.filter(AuditLogORM.action.like("PLAN_LIMIT_ALERT_WARN_%")).count()
            ),
            "danger_last_24h": int(
                alerts_24h.filter(
                    AuditLogORM.action.like("PLAN_LIMIT_ALERT_DANGER_%")
                ).count()
            ),
            "latest_created_at": alerts_base.with_entities(
                func.max(AuditLogORM.created_at)
            ).scalar(),
        }

        failing_since = now - timedelta(hours=failing_projects_window_hours)
        failing_rows = (
            self.session.query(
                ProjectImportRunORM,
                ProjectORM.name.label("project_name"),
            )
            .outerjoin(
                ProjectORM,
                and_(
                    ProjectORM.id == ProjectImportRunORM.project_id,
                    ProjectORM.company_id == ProjectImportRunORM.company_id,
                ),
            )
            .filter(
                ProjectImportRunORM.company_id == company_id,
                ProjectImportRunORM.created_at >= failing_since,
                ProjectImportRunORM.import_mode.in_(["import", "import_retry"]),
            )
            .order_by(ProjectImportRunORM.created_at.desc())
            .all()
        )

        failures_by_project: dict[uuid.UUID, dict] = {}
        for run, project_name in failing_rows:
            payload = run.result_payload if isinstance(run.result_payload, dict) else {}
            errors_count = _payload_errors_count(payload)
            if errors_count <= 0:
                continue
            bucket = failures_by_project.get(run.project_id)
            if bucket is None:
                bucket = {
                    "project_id": run.project_id,
                    "project_name": project_name or str(run.project_id),
                    "failure_runs": 0,
                    "last_run_at": run.created_at,
                    "last_error": _payload_first_error(payload),
                }
                failures_by_project[run.project_id] = bucket
            bucket["failure_runs"] += 1
            if run.created_at > bucket["last_run_at"]:
                bucket["last_run_at"] = run.created_at
                bucket["last_error"] = _payload_first_error(payload)

        top_failing_projects = sorted(
            failures_by_project.values(),
            key=lambda item: (
                -int(item["failure_runs"]),
                -item["last_run_at"].timestamp(),
            ),
        )[:5]

        return {
            "imports": imports,
            "outbox": outbox,
            "alerts": alerts,
            "top_failing_projects": top_failing_projects,
        }

    def operations_sla_history(
        self,
        *,
        company_id: uuid.UUID,
        now: datetime,
        days: int,
    ) -> dict:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        days = max(1, min(int(days), 90))
        utc_now = now.astimezone(timezone.utc)
        day_end = utc_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )
        day_start = day_end - timedelta(days=days)

        buckets: dict[str, dict] = {}
        for idx in range(days):
            d = (day_start + timedelta(days=idx)).date()
            key = d.isoformat()
            buckets[key] = {
                "day": d,
                "import_runs": 0,
                "risky_import_runs": 0,
                "outbox_total": 0,
                "outbox_failed": 0,
                "danger_alerts_count": 0,
            }

        import_rows = (
            self.session.query(ProjectImportRunORM)
            .filter(
                ProjectImportRunORM.company_id == company_id,
                ProjectImportRunORM.created_at >= day_start,
                ProjectImportRunORM.created_at < day_end,
                ProjectImportRunORM.import_mode.in_(["import", "import_retry"]),
            )
            .all()
        )
        for row in import_rows:
            key = row.created_at.astimezone(timezone.utc).date().isoformat()
            bucket = buckets.get(key)
            if bucket is None:
                continue
            bucket["import_runs"] += 1
            status = _import_run_status(row)
            if status in {"FAILED", "PARTIAL"}:
                bucket["risky_import_runs"] += 1

        outbox_rows = (
            self.session.query(
                func.date_trunc("day", OutboxMessageORM.created_at).label("day"),
                func.count(OutboxMessageORM.id).label("total"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (
                                    (OutboxMessageORM.status == OutboxStatus.FAILED)
                                    | (
                                        OutboxMessageORM.delivery_status
                                        == DeliveryStatus.FAILED
                                    )
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("failed"),
            )
            .filter(
                OutboxMessageORM.company_id == company_id,
                OutboxMessageORM.created_at >= day_start,
                OutboxMessageORM.created_at < day_end,
            )
            .group_by(func.date_trunc("day", OutboxMessageORM.created_at))
            .all()
        )
        for day, total, failed in outbox_rows:
            day_value = day if day.tzinfo is not None else day.replace(tzinfo=timezone.utc)
            key = day_value.astimezone(timezone.utc).date().isoformat()
            bucket = buckets.get(key)
            if bucket is None:
                continue
            bucket["outbox_total"] = int(total or 0)
            bucket["outbox_failed"] = int(failed or 0)

        alerts_rows = (
            self.session.query(
                func.date_trunc("day", AuditLogORM.created_at).label("day"),
                func.count(AuditLogORM.id).label("danger_alerts_count"),
            )
            .filter(
                AuditLogORM.company_id == company_id,
                AuditLogORM.action.like("PLAN_LIMIT_ALERT_DANGER_%"),
                AuditLogORM.created_at >= day_start,
                AuditLogORM.created_at < day_end,
            )
            .group_by(func.date_trunc("day", AuditLogORM.created_at))
            .all()
        )
        for day, count in alerts_rows:
            day_value = day if day.tzinfo is not None else day.replace(tzinfo=timezone.utc)
            key = day_value.astimezone(timezone.utc).date().isoformat()
            bucket = buckets.get(key)
            if bucket is None:
                continue
            bucket["danger_alerts_count"] = int(count or 0)

        points: list[dict] = []
        for key in sorted(buckets.keys()):
            bucket = buckets[key]
            import_runs = int(bucket["import_runs"])
            risky_import_runs = int(bucket["risky_import_runs"])
            outbox_total = int(bucket["outbox_total"])
            outbox_failed = int(bucket["outbox_failed"])
            danger_alerts_count = int(bucket["danger_alerts_count"])
            import_failure_rate = (
                round((risky_import_runs / import_runs) * 100.0, 2)
                if import_runs > 0
                else 0.0
            )
            outbox_failed_rate = (
                round((outbox_failed / outbox_total) * 100.0, 2)
                if outbox_total > 0
                else 0.0
            )
            points.append(
                {
                    "day": bucket["day"],
                    "import_runs": import_runs,
                    "risky_import_runs": risky_import_runs,
                    "import_failure_rate_pct": import_failure_rate,
                    "outbox_total": outbox_total,
                    "outbox_failed": outbox_failed,
                    "outbox_failed_rate_pct": outbox_failed_rate,
                    "danger_alerts_count": danger_alerts_count,
                }
            )

        return {
            "days": days,
            "points": points,
        }

    def limit_alerts(
        self,
        *,
        company_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        rows = (
            self.session.query(AuditLogORM)
            .filter(
                AuditLogORM.company_id == company_id,
                AuditLogORM.action.like("PLAN_LIMIT_ALERT_%"),
            )
            .order_by(AuditLogORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        items: list[dict] = []
        for row in rows:
            payload = row.after or {}
            items.append(
                {
                    "id": row.id,
                    "created_at": row.created_at,
                    "action": row.action,
                    "level": payload.get("level"),
                    "metric": payload.get("metric"),
                    "current": payload.get("current"),
                    "max": payload.get("max"),
                    "utilization_pct": payload.get("utilization_pct"),
                    "plan_code": payload.get("plan_code"),
                }
            )
        return items

    def issues_analytics(
        self,
        *,
        company_id: uuid.UUID,
        now: datetime,
        days: int,
    ) -> dict:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        days = max(7, min(int(days), 90))
        utc_now = now.astimezone(timezone.utc)
        day_end = utc_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )
        day_start = day_end - timedelta(days=days)
        mttr_since = utc_now - timedelta(days=days)

        base = self.session.query(IssueORM).filter(IssueORM.company_id == company_id)

        total_issues = int(base.count())
        open_issues = int(base.filter(IssueORM.status == IssueStatus.OPEN).count())
        closed_issues = int(base.filter(IssueORM.status == IssueStatus.CLOSED).count())
        overdue_open_issues = int(
            base.filter(
                IssueORM.status == IssueStatus.OPEN,
                IssueORM.due_at.isnot(None),
                IssueORM.due_at < utc_now,
            ).count()
        )
        blocked_open_issues = int(
            base.filter(
                IssueORM.status == IssueStatus.OPEN,
                IssueORM.workflow_state == IssueWorkflowState.BLOCKED,
            ).count()
        )
        p1_open_issues = int(
            base.filter(
                IssueORM.status == IssueStatus.OPEN,
                IssueORM.priority == IssuePriority.P1,
            ).count()
        )
        overdue_open_rate_pct = (
            round((overdue_open_issues / open_issues) * 100.0, 2)
            if open_issues > 0
            else 0.0
        )

        workflow_rows = (
            base.with_entities(
                IssueORM.workflow_state,
                func.count(IssueORM.id),
            )
            .filter(IssueORM.status == IssueStatus.OPEN)
            .group_by(IssueORM.workflow_state)
            .all()
        )
        backlog_by_workflow = {state.value: 0 for state in IssueWorkflowState}
        for workflow_state, count in workflow_rows:
            key = workflow_state.value if hasattr(workflow_state, "value") else str(workflow_state)
            backlog_by_workflow[key] = int(count or 0)

        priority_rows = (
            base.with_entities(
                IssueORM.priority,
                func.count(IssueORM.id),
            )
            .filter(IssueORM.status == IssueStatus.OPEN)
            .group_by(IssueORM.priority)
            .all()
        )
        backlog_by_priority = {priority.value: 0 for priority in IssuePriority}
        for priority, count in priority_rows:
            key = priority.value if hasattr(priority, "value") else str(priority)
            backlog_by_priority[key] = int(count or 0)

        mttr_rows = (
            base.with_entities(IssueORM.created_at, IssueORM.updated_at)
            .filter(
                IssueORM.status == IssueStatus.CLOSED,
                IssueORM.updated_at >= mttr_since,
                IssueORM.updated_at <= utc_now,
            )
            .all()
        )
        mttr_samples: list[float] = []
        for created_at, updated_at in mttr_rows:
            if created_at is None or updated_at is None:
                continue
            duration_hours = (updated_at - created_at).total_seconds() / 3600.0
            if duration_hours >= 0:
                mttr_samples.append(duration_hours)
        mttr_hours = round(sum(mttr_samples) / len(mttr_samples), 2) if mttr_samples else 0.0
        mttr_p50_hours = round(float(median(mttr_samples)), 2) if mttr_samples else 0.0

        opened_rows = (
            self.session.query(
                func.date_trunc("day", IssueORM.created_at).label("day"),
                func.count(IssueORM.id).label("opened"),
            )
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.created_at >= day_start,
                IssueORM.created_at < day_end,
            )
            .group_by(func.date_trunc("day", IssueORM.created_at))
            .all()
        )
        closed_rows = (
            self.session.query(
                func.date_trunc("day", IssueORM.updated_at).label("day"),
                func.count(IssueORM.id).label("closed"),
            )
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.status == IssueStatus.CLOSED,
                IssueORM.updated_at >= day_start,
                IssueORM.updated_at < day_end,
            )
            .group_by(func.date_trunc("day", IssueORM.updated_at))
            .all()
        )

        opened_by_day: dict[str, int] = {}
        for day, opened in opened_rows:
            value = day if day.tzinfo is not None else day.replace(tzinfo=timezone.utc)
            opened_by_day[value.astimezone(timezone.utc).date().isoformat()] = int(opened or 0)

        closed_by_day: dict[str, int] = {}
        for day, closed in closed_rows:
            value = day if day.tzinfo is not None else day.replace(tzinfo=timezone.utc)
            closed_by_day[value.astimezone(timezone.utc).date().isoformat()] = int(closed or 0)

        initial_backlog = int(
            self.session.query(func.count(IssueORM.id))
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.created_at < day_start,
                or_(
                    IssueORM.status != IssueStatus.CLOSED,
                    IssueORM.updated_at >= day_start,
                ),
            )
            .scalar()
            or 0
        )

        trend: list[dict] = []
        backlog_open_end = max(initial_backlog, 0)
        for idx in range(days):
            day_value = (day_start + timedelta(days=idx)).date()
            key = day_value.isoformat()
            opened = int(opened_by_day.get(key, 0))
            closed = int(closed_by_day.get(key, 0))
            backlog_open_end = max(backlog_open_end + opened - closed, 0)
            trend.append(
                {
                    "day": day_value,
                    "opened": opened,
                    "closed": closed,
                    "backlog_open_end": backlog_open_end,
                }
            )

        return {
            "days": days,
            "summary": {
                "total_issues": total_issues,
                "open_issues": open_issues,
                "closed_issues": closed_issues,
                "overdue_open_issues": overdue_open_issues,
                "blocked_open_issues": blocked_open_issues,
                "p1_open_issues": p1_open_issues,
                "overdue_open_rate_pct": overdue_open_rate_pct,
                "mttr_hours": mttr_hours,
                "mttr_p50_hours": mttr_p50_hours,
                "mttr_sample_size": len(mttr_samples),
                "backlog_by_workflow": backlog_by_workflow,
                "backlog_by_priority": backlog_by_priority,
            },
            "trend": trend,
        }
