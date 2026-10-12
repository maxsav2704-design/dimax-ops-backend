from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.modules.doors.infrastructure.models import DoorORM
from app.shared.domain.errors import Conflict


@dataclass(frozen=True)
class ExecutionEvidence:
    reason: str | None = None
    legacy_queue: bool = False
    assignment_started_at: datetime | None = None

    @property
    def reviewable(self):
        return self.reason in {
            "ASSIGNMENT_EVIDENCE_REQUIRED", "HISTORICAL_PRICE_REVIEW", "LEGACY_EXECUTION_REVIEW",
        }

    def require_automatic(self):
        if self.reason:
            raise Conflict("Execution evidence requires administrator review", field="price_list_id",
                           meta={"reason": self.reason})
        return self.legacy_queue


class ExecutionAuthority:
    """Device dates and price IDs are claims, not proof of historic price entitlement."""

    @staticmethod
    def inspect(uow, *, company_id, project_id, installer_id, performed_at, received_at,
                has_timezone, door_id=None, lock_assignments=False):
        if performed_at is None:
            return ExecutionEvidence("MISSING_EXECUTION_TIME")
        if has_timezone is not True or performed_at.utcoffset() is None:
            return ExecutionEvidence("INVALID_EXECUTION_TIME")
        if received_at is None or performed_at > received_at:
            return ExecutionEvidence("INVALID_EXECUTION_TIME")
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if project is None or performed_at < project.created_at:
            return ExecutionEvidence("INVALID_EXECUTION_TIME")
        query = select(DoorORM.created_at, DoorORM.assignment_started_at).where(
            DoorORM.company_id == company_id, DoorORM.project_id == project_id,
            DoorORM.installer_id == installer_id,
        )
        if door_id is not None:
            query = query.where(DoorORM.id == door_id)
        if lock_assignments:
            query = query.order_by(DoorORM.id).with_for_update()
        assignments = uow.session.execute(query).all()
        if not assignments:
            return ExecutionEvidence("WORK_UNAVAILABLE")
        if door_id is not None and performed_at < assignments[0].created_at:
            return ExecutionEvidence("INVALID_EXECUTION_TIME")
        boundaries = [row.assignment_started_at for row in assignments if row.assignment_started_at is not None]
        boundary = min(boundaries) if boundaries else None
        if boundary is None or performed_at < boundary:
            return ExecutionEvidence("ASSIGNMENT_EVIDENCE_REQUIRED", assignment_started_at=boundary)
        execution = uow.price_lists.activation_at(company_id, performed_at)
        receipt = uow.price_lists.activation_at(company_id, received_at)
        if execution is None:
            if receipt is not None:
                return ExecutionEvidence("LEGACY_EXECUTION_REVIEW", assignment_started_at=boundary)
            # Only server receipt predating activation proves an old queue, never a missing price ID.
            return ExecutionEvidence(legacy_queue=True, assignment_started_at=boundary)
        if receipt is None or execution.id != receipt.id:
            return ExecutionEvidence("HISTORICAL_PRICE_REVIEW", assignment_started_at=boundary)
        return ExecutionEvidence(assignment_started_at=boundary)
