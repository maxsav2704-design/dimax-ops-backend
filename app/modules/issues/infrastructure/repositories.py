from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.modules.doors.infrastructure.models import DoorORM
from app.modules.issues.domain.enums import IssueStatus, IssueWorkflowState
from app.modules.issues.infrastructure.models import IssueORM

SYNC_RISK_TITLE = "SYNC_RISK"
DELIVERY_OUTBOX_RISK_TITLE = "DELIVERY_OUTBOX_RISK"


class IssueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_door(
        self, *, company_id: uuid.UUID, door_id: uuid.UUID
    ) -> IssueORM | None:
        return (
            self.session.query(IssueORM)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.door_id == door_id,
            )
            .one_or_none()
        )

    def get(
        self, *, company_id: uuid.UUID, issue_id: uuid.UUID
    ) -> IssueORM | None:
        return (
            self.session.query(IssueORM)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.id == issue_id,
            )
            .one_or_none()
        )

    def list_by_ids(
        self,
        *,
        company_id: uuid.UUID,
        issue_ids: list[uuid.UUID],
    ) -> list[IssueORM]:
        if not issue_ids:
            return []
        return (
            self.session.query(IssueORM)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.id.in_(issue_ids),
            )
            .all()
        )

    def list(
        self,
        *,
        company_id: uuid.UUID,
        status: IssueStatus | None,
        owner_user_id: uuid.UUID | None,
        workflow_state: IssueWorkflowState | None,
        overdue_only: bool,
        project_id: uuid.UUID | None,
        door_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> list[IssueORM]:
        q = (
            self.session.query(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(IssueORM.company_id == company_id)
        )
        if status is not None:
            q = q.filter(IssueORM.status == status)
        if owner_user_id is not None:
            q = q.filter(IssueORM.owner_user_id == owner_user_id)
        if workflow_state is not None:
            q = q.filter(IssueORM.workflow_state == workflow_state)
        if overdue_only:
            q = q.filter(
                IssueORM.status == IssueStatus.OPEN,
                IssueORM.due_at.isnot(None),
                IssueORM.due_at < datetime.now(timezone.utc),
            )
        if project_id is not None:
            q = q.filter(DoorORM.project_id == project_id)
        if door_id is not None:
            q = q.filter(IssueORM.door_id == door_id)
        return (
            q.order_by(IssueORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def list_open_by_project(
        self, *, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> list[IssueORM]:
        return (
            self.session.query(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                DoorORM.project_id == project_id,
                IssueORM.status == IssueStatus.OPEN,
            )
            .order_by(IssueORM.created_at.desc())
            .all()
        )

    def list_open_by_project_for_installer(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> list[IssueORM]:
        return (
            self.session.query(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                DoorORM.project_id == project_id,
                DoorORM.installer_id == installer_id,
                IssueORM.status == IssueStatus.OPEN,
            )
            .order_by(IssueORM.created_at.desc())
            .all()
        )

    def _find_sync_risk_issue(
        self, *, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> IssueORM | None:
        return (
            self.session.query(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                DoorORM.project_id == project_id,
                IssueORM.title == SYNC_RISK_TITLE,
            )
            .first()
        )

    def _find_delivery_outbox_risk_issue(
        self, *, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> IssueORM | None:
        return (
            self.session.query(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                DoorORM.project_id == project_id,
                IssueORM.title == DELIVERY_OUTBOX_RISK_TITLE,
            )
            .first()
        )

    def upsert_sync_risk(
        self, *, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> uuid.UUID | None:
        row = self._find_sync_risk_issue(
            company_id=company_id, project_id=project_id
        )
        if row and row.status == IssueStatus.OPEN:
            return row.id
        if row and row.status != IssueStatus.OPEN:
            row.status = IssueStatus.OPEN
            row.details = "Installer sync is in DANGER state (offline/lag)."
            self.session.flush()
            return row.id
        door = (
            self.session.query(DoorORM)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.project_id == project_id,
            )
            .limit(1)
            .first()
        )
        if not door:
            return None
        new = IssueORM(
            company_id=company_id,
            door_id=door.id,
            status=IssueStatus.OPEN,
            title=SYNC_RISK_TITLE,
            details="Installer sync is in DANGER state (offline/lag).",
        )
        self.session.add(new)
        self.session.flush()
        return new.id

    def close_sync_risk(
        self, *, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> bool:
        row = self._find_sync_risk_issue(
            company_id=company_id, project_id=project_id
        )
        if not row or row.status != IssueStatus.OPEN:
            return False
        row.status = IssueStatus.CLOSED
        self.session.flush()
        return True

    def upsert_delivery_outbox_risk(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        details: str,
    ) -> tuple[uuid.UUID | None, bool]:
        row = self._find_delivery_outbox_risk_issue(
            company_id=company_id,
            project_id=project_id,
        )
        if row and row.status == IssueStatus.OPEN:
            row.details = details[:2000]
            self.session.flush()
            return row.id, False
        if row and row.status != IssueStatus.OPEN:
            row.status = IssueStatus.OPEN
            row.details = details[:2000]
            self.session.flush()
            return row.id, True

        door = (
            self.session.query(DoorORM)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.project_id == project_id,
            )
            .limit(1)
            .first()
        )
        if not door:
            return None, False

        new = IssueORM(
            company_id=company_id,
            door_id=door.id,
            status=IssueStatus.OPEN,
            title=DELIVERY_OUTBOX_RISK_TITLE,
            details=details[:2000],
        )
        self.session.add(new)
        self.session.flush()
        return new.id, True

    def close_delivery_outbox_risk(
        self, *, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> tuple[uuid.UUID | None, bool]:
        row = self._find_delivery_outbox_risk_issue(
            company_id=company_id,
            project_id=project_id,
        )
        if not row or row.status != IssueStatus.OPEN:
            return (row.id if row else None), False
        row.status = IssueStatus.CLOSED
        self.session.flush()
        return row.id, True

    def save(self, issue: IssueORM) -> None:
        self.session.add(issue)
