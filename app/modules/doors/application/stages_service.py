"""Work stages (spec 3.3, step 3): a door may be installed in stages by different installers.

Rules kept here: the admin plans stages before execution; assignment history is preserved; one
immutable fact per door stage; when every required stage of the plan has a fact the door becomes
INSTALLED through the same locks, transition record and project recalculation as before, but
WITHOUT the legacy full-installation earning (stage earnings are step 4). A door with a work plan
cannot be installed through the legacy paths, so nothing is ever accrued twice. Everything is
behind WORK_STAGES_ENABLED; doors without a plan behave exactly as before.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.config import settings
from app.modules.audit.application.service import AuditService
from app.modules.doors.application.completion import resolve_installation_time
from app.modules.doors.application.transition_recorder import record_door_transition
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.domain.errors import DoorNotAssigned
from app.modules.doors.infrastructure.stage_models import (
    STAGE_CODE_PATTERN, DoorStageAssignmentORM, DoorStageFactORM, DoorTypeStagePlanItemORM,
    DoorTypeStagePlanORM, DoorWorkPlanORM, WorkStageDefinitionORM,
)
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.earnings.application.factory_pricing import FactoryEarningsPricing
from app.modules.issues.application.sync_payload import publish_issue_change
from app.modules.issues.domain.enums import IssueStatus, IssueWorkflowState
from app.modules.projects.application.status_service import ProjectStatusService
from app.shared.domain.errors import Conflict, NotFound, ValidationError

_CODE = re.compile(STAGE_CODE_PATTERN)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def current_door_plan(session, door_id: uuid.UUID) -> DoorWorkPlanORM | None:
    return session.scalar(select(DoorWorkPlanORM).where(DoorWorkPlanORM.door_id == door_id, DoorWorkPlanORM.replaced_at.is_(None)))


def ensure_not_stage_door(uow, door) -> None:
    """Legacy full-installation paths refuse doors that are installed by stages (no double accrual)."""
    if current_door_plan(uow.session, door.id) is not None:
        raise Conflict("Door is installed by stages; complete its stages instead",
                       details={"door_id": str(door.id), "installed_by_stages": True})


class WorkStagesService:
    @staticmethod
    def enabled() -> bool:
        return bool(settings.WORK_STAGES_ENABLED)

    @classmethod
    def _require_enabled(cls) -> None:
        if not cls.enabled():
            raise Conflict("Work stages are not enabled on this server")

    # ---- catalog ------------------------------------------------------------------------------
    @classmethod
    def definitions(cls, uow, company_id: uuid.UUID, *, include_inactive: bool = True):
        cls._require_enabled()
        stmt = select(WorkStageDefinitionORM).where(WorkStageDefinitionORM.company_id == company_id)
        if not include_inactive:
            stmt = stmt.where(WorkStageDefinitionORM.is_active.is_(True))
        return list(uow.session.scalars(stmt.order_by(WorkStageDefinitionORM.sort_order, WorkStageDefinitionORM.code)).all())

    @classmethod
    def create_definition(cls, uow, *, company_id, actor_user_id, code: str, name: str, sort_order: int):
        cls._require_enabled()
        FactoryEarningsPricing.lock_company(uow, company_id)
        code = code.strip().upper()
        if not _CODE.match(code):
            raise ValidationError("Stage code: A-Z, 0-9 and underscores, starting with a letter", field="code")
        if uow.session.scalar(select(WorkStageDefinitionORM.id).where(
                WorkStageDefinitionORM.company_id == company_id, WorkStageDefinitionORM.code == code)):
            raise Conflict("Stage code already exists", details={"code": code})
        row = WorkStageDefinitionORM(id=uuid.uuid4(), company_id=company_id, code=code, name=name.strip(), sort_order=sort_order, is_active=True)
        uow.session.add(row)
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id, entity_type="work_stage", entity_id=row.id,
                         action="CREATE", after={"code": code, "name": row.name, "sort_order": sort_order})
        return row

    @classmethod
    def update_definition(cls, uow, *, company_id, actor_user_id, code: str, name=None, sort_order=None, is_active=None):
        cls._require_enabled()
        FactoryEarningsPricing.lock_company(uow, company_id)
        row = uow.session.scalar(select(WorkStageDefinitionORM).where(
            WorkStageDefinitionORM.company_id == company_id, WorkStageDefinitionORM.code == code).with_for_update())
        if row is None:
            raise NotFound("Stage not found", details={"code": code})
        before = {"name": row.name, "sort_order": row.sort_order, "is_active": row.is_active}
        if name is not None:
            row.name = name.strip()
        if sort_order is not None:
            row.sort_order = sort_order
        if is_active is not None:
            row.is_active = is_active
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id, entity_type="work_stage", entity_id=row.id,
                         action="UPDATE", before=before, after={"name": row.name, "sort_order": row.sort_order, "is_active": row.is_active})
        return row

    # ---- door type plans -----------------------------------------------------------------------
    @staticmethod
    def plan_items(session, plan_id: uuid.UUID):
        return list(session.scalars(select(DoorTypeStagePlanItemORM).where(DoorTypeStagePlanItemORM.plan_id == plan_id)
                                    .order_by(DoorTypeStagePlanItemORM.sequence)).all())

    @classmethod
    def plans(cls, uow, company_id: uuid.UUID, door_type_id: uuid.UUID):
        cls._require_enabled()
        rows = list(uow.session.scalars(select(DoorTypeStagePlanORM).where(
            DoorTypeStagePlanORM.company_id == company_id, DoorTypeStagePlanORM.door_type_id == door_type_id)
            .order_by(DoorTypeStagePlanORM.version.desc())).all())
        latest = rows[0].version if rows else 0
        return rows, latest

    @classmethod
    def create_plan(cls, uow, *, company_id, actor_user_id, door_type_id, expected_latest_version: int, reason: str, items: list):
        cls._require_enabled()
        FactoryEarningsPricing.lock_company(uow, company_id)
        door_type = uow.session.get(DoorTypeORM, door_type_id)
        if door_type is None or door_type.company_id != company_id or door_type.deleted_at is not None:
            raise NotFound("Door type not found", details={"door_type_id": str(door_type_id)})
        _, latest = cls.plans(uow, company_id, door_type_id)
        if latest != expected_latest_version:
            raise Conflict("Stage plan changed; reload before creating a new version", meta={"latest_version": latest})
        if not items:
            raise ValidationError("A stage plan needs at least one stage", field="items")
        codes = [item.stage_code for item in items]
        if len(set(codes)) != len(codes):
            raise ValidationError("A stage appears twice in the plan", field="items")
        if not any(item.required for item in items):
            raise ValidationError("A stage plan needs at least one required stage", field="items")
        active = {row.code for row in cls.definitions(uow, company_id, include_inactive=False)}
        missing = sorted(set(codes) - active)
        if missing:
            raise ValidationError("Unknown or inactive stages: " + ", ".join(missing), field="items")
        plan = DoorTypeStagePlanORM(id=uuid.uuid4(), company_id=company_id, door_type_id=door_type_id, version=latest + 1,
                                    reason=reason.strip(), created_by=actor_user_id, created_at=utcnow())
        uow.session.add(plan)
        uow.session.flush()
        for sequence, item in enumerate(items, start=1):
            uow.session.add(DoorTypeStagePlanItemORM(id=uuid.uuid4(), company_id=company_id, plan_id=plan.id,
                                                     stage_code=item.stage_code, required=item.required, sequence=sequence))
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id, entity_type="door_type_stage_plan", entity_id=plan.id,
                         action="CREATE", reason=reason[:500],
                         after={"door_type_id": str(door_type_id), "version": plan.version,
                                "stages": [{"code": item.stage_code, "required": item.required} for item in items]})
        return plan

    # ---- door plan and assignments ---------------------------------------------------------------
    @staticmethod
    def _locked_door(uow, company_id, door_id, *, active_project_only=False):
        FactoryEarningsPricing.lock_company(uow, company_id)
        door = uow.doors.get(company_id=company_id, door_id=door_id, for_update=True, active_project_only=active_project_only)
        if door is None:
            raise NotFound("Door not found", details={"door_id": str(door_id)})
        return door

    @staticmethod
    def facts(session, door_id: uuid.UUID):
        return list(session.scalars(select(DoorStageFactORM).where(DoorStageFactORM.door_id == door_id)).all())

    @staticmethod
    def current_assignments(session, door_id: uuid.UUID):
        return {row.stage_code: row for row in session.scalars(select(DoorStageAssignmentORM).where(
            DoorStageAssignmentORM.door_id == door_id, DoorStageAssignmentORM.replaced_at.is_(None))).all()}

    @classmethod
    def apply_plan(cls, uow, *, company_id, actor_user_id, door_id, plan_id):
        cls._require_enabled()
        door = cls._locked_door(uow, company_id, door_id)
        if door.is_locked or door.status == DoorStatus.INSTALLED:
            raise Conflict("An installed door cannot be re-planned", details={"door_id": str(door_id)})
        plan = uow.session.get(DoorTypeStagePlanORM, plan_id)
        if plan is None or plan.company_id != company_id:
            raise NotFound("Stage plan not found", details={"plan_id": str(plan_id)})
        if plan.door_type_id != door.door_type_id:
            raise ValidationError("The stage plan belongs to another door type", field="plan_id")
        if cls.facts(uow.session, door_id):
            raise Conflict("Stages of this door were already executed; the plan cannot change", details={"door_id": str(door_id)})
        current = current_door_plan(uow.session, door_id)
        if current is not None and current.plan_id == plan_id:
            return current
        now = utcnow()
        if current is not None:
            current.replaced_at, current.replaced_by = now, actor_user_id
            uow.session.flush()
        row = DoorWorkPlanORM(id=uuid.uuid4(), company_id=company_id, door_id=door_id, plan_id=plan_id,
                              applied_by=actor_user_id, applied_at=now)
        uow.session.add(row)
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id, entity_type="door", entity_id=door_id,
                         action="DOOR_WORK_PLAN", before={"plan_id": str(current.plan_id)} if current else None,
                         after={"plan_id": str(plan_id), "version": plan.version})
        return row

    @classmethod
    def assign_stage(cls, uow, *, company_id, actor_user_id, door_id, stage_code, installer_id):
        cls._require_enabled()
        door = cls._locked_door(uow, company_id, door_id)
        plan = current_door_plan(uow.session, door_id)
        if plan is None:
            raise Conflict("Apply a stage plan to the door first", details={"door_id": str(door_id)})
        if stage_code not in {item.stage_code for item in cls.plan_items(uow.session, plan.plan_id)}:
            raise ValidationError("Stage is not part of the door's plan", field="stage_code")
        installer = uow.installers.get(company_id=company_id, installer_id=installer_id)
        if installer is None or not installer.is_active or getattr(installer, "deleted_at", None) is not None:
            raise ValidationError("Installer is unavailable", field="installer_id")
        if any(fact.stage_code == stage_code for fact in cls.facts(uow.session, door_id)):
            raise Conflict("This stage was already executed; its executor cannot change", details={"stage_code": stage_code})
        current = cls.current_assignments(uow.session, door_id).get(stage_code)
        if current is not None and current.installer_id == installer_id:
            return current
        now = utcnow()
        if current is not None:
            current.replaced_at, current.replaced_by = now, actor_user_id
            uow.session.flush()
        row = DoorStageAssignmentORM(id=uuid.uuid4(), company_id=company_id, door_id=door_id, stage_code=stage_code,
                                     installer_id=installer_id, assigned_by=actor_user_id, assigned_at=now)
        uow.session.add(row)
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id, entity_type="door", entity_id=door_id,
                         action="DOOR_STAGE_ASSIGN", before={"installer_id": str(current.installer_id)} if current else None,
                         after={"stage_code": stage_code, "installer_id": str(installer_id)})
        return row

    # ---- view ---------------------------------------------------------------------------------
    @classmethod
    def door_stages(cls, uow, *, company_id, door_id, installer_id=None) -> dict | None:
        """Plan, assignments and facts of one door. For an installer: only doors where they hold an assignment."""
        door = uow.doors.get(company_id=company_id, door_id=door_id)
        if door is None:
            raise NotFound("Door not found", details={"door_id": str(door_id)})
        plan = current_door_plan(uow.session, door_id)
        if plan is None:
            return None
        assignments = cls.current_assignments(uow.session, door_id)
        if installer_id is not None and not any(a.installer_id == installer_id for a in assignments.values()):
            raise NotFound("Door not found", details={"door_id": str(door_id)})
        facts = {fact.stage_code: fact for fact in cls.facts(uow.session, door_id)}
        definitions = {row.code: row for row in uow.session.scalars(select(WorkStageDefinitionORM).where(
            WorkStageDefinitionORM.company_id == company_id)).all()}
        version = uow.session.get(DoorTypeStagePlanORM, plan.plan_id)
        stages = []
        for item in cls.plan_items(uow.session, plan.plan_id):
            assignment, fact = assignments.get(item.stage_code), facts.get(item.stage_code)
            stages.append({
                "stage_code": item.stage_code, "name": definitions[item.stage_code].name, "required": item.required,
                "sequence": item.sequence,
                "installer_id": assignment.installer_id if assignment else None,
                "assignment_id": assignment.id if assignment else None,
                "completed_at": fact.happened_at if fact else None,
                "completed_by": fact.installer_id if fact else None,
                "fact_id": fact.id if fact else None,
            })
        required_total = sum(1 for s in stages if s["required"])
        required_done = sum(1 for s in stages if s["required"] and s["fact_id"])
        return {"door_id": door_id, "door_status": door.status.value if hasattr(door.status, "value") else str(door.status),
                "door_version": int(door.version or 0), "plan_id": plan.plan_id, "plan_version": version.version,
                "stages": stages, "required_total": required_total, "required_done": required_done,
                "installed_by_stages": bool(door.is_locked and door.status == DoorStatus.INSTALLED)}

    # ---- execution --------------------------------------------------------------------------------
    @classmethod
    def complete_stage(cls, uow, *, company_id, actor_user_id, installer_id, door_id, stage_code, happened_at=None,
                       source="API", client_event_id=None, request_id=None) -> dict:
        cls._require_enabled()
        door = cls._locked_door(uow, company_id, door_id, active_project_only=True)
        plan = current_door_plan(uow.session, door_id)
        if plan is None:
            raise Conflict("Door is not installed by stages", details={"door_id": str(door_id)})
        items = {item.stage_code: item for item in cls.plan_items(uow.session, plan.plan_id)}
        if stage_code not in items:
            raise ValidationError("Stage is not part of the door's plan", field="stage_code")
        assignment = cls.current_assignments(uow.session, door_id).get(stage_code)
        if assignment is None or assignment.installer_id != installer_id:
            raise DoorNotAssigned("Stage is not assigned to this installer", details={"door_id": str(door_id), "stage_code": stage_code})
        facts = {fact.stage_code: fact for fact in cls.facts(uow.session, door_id)}
        existing = facts.get(stage_code)
        received_at = utcnow()
        if existing is not None:
            replay = (client_event_id is not None and existing.client_event_id == client_event_id) or \
                     (request_id is not None and existing.request_id == request_id)
            if replay and existing.installer_id == installer_id:
                return cls._completion_result(door, items, facts, applied=False)
            raise Conflict("This stage is already completed", details={"door_id": str(door_id), "stage_code": stage_code})
        if door.is_locked:
            raise Conflict("Door is locked (already installed). Admin override required.", details={"door_id": str(door_id)})
        fact = DoorStageFactORM(id=uuid.uuid4(), company_id=company_id, door_id=door_id, stage_code=stage_code, plan_id=plan.plan_id,
                                assignment_id=assignment.id, installer_id=installer_id,
                                happened_at=resolve_installation_time(happened_at, received_at=received_at), received_at=received_at,
                                source=source, client_event_id=client_event_id, request_id=request_id,
                                created_by=actor_user_id, created_at=received_at)
        uow.session.add(fact)
        uow.session.flush()
        facts[stage_code] = fact
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id, entity_type="door", entity_id=door_id,
                         action="DOOR_STAGE_COMPLETE", after={"stage_code": stage_code, "installer_id": str(installer_id),
                                                              "happened_at": fact.happened_at.isoformat(), "source": source,
                                                              "creates_earning": False})
        if all(code in facts for code, item in items.items() if item.required):
            cls._install_by_stages(uow, company_id=company_id, actor_user_id=actor_user_id, door=door, facts=facts, source=source)
        return cls._completion_result(door, items, facts, applied=True)

    @staticmethod
    def _completion_result(door, items, facts, *, applied: bool) -> dict:
        required = [code for code, item in items.items() if item.required]
        return {"id": door.id, "status": door.status.value if hasattr(door.status, "value") else str(door.status),
                "version": int(door.version or 0), "applied": applied,
                "required_total": len(required), "required_done": sum(1 for code in required if code in facts),
                "door_installed": door.status == DoorStatus.INSTALLED}

    @staticmethod
    def _install_by_stages(uow, *, company_id, actor_user_id, door, facts, source) -> None:
        """Every required stage is done: the door is INSTALLED like before, minus the legacy full-door earning."""
        from_status = door.status
        door.status = DoorStatus.INSTALLED
        door.installed_at = max(fact.happened_at for fact in facts.values())
        door.is_locked = True
        door.reason_id = None
        door.comment = None
        door.version = int(door.version or 0) + 1
        uow.doors.save(door)
        issue = uow.issues.get_by_door(company_id=company_id, door_id=door.id)
        if issue and issue.status != IssueStatus.CLOSED:
            issue.status = IssueStatus.CLOSED
            issue.workflow_state = IssueWorkflowState.CLOSED
            uow.issues.save(issue)
            publish_issue_change(uow, issue=issue, door=door)
        ProjectStatusService.recalc_and_set(uow=uow, company_id=company_id, project_id=door.project_id)
        record_door_transition(uow, company_id=company_id, actor_user_id=actor_user_id, door=door, from_status=from_status,
                               source=source, reason="All required stages completed")
