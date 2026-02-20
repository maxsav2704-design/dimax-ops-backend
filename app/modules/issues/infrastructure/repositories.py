from __future__ import annotations

import uuid
from sqlalchemy.orm import Session

from app.modules.doors.infrastructure.models import DoorORM
from app.modules.issues.domain.enums import IssueStatus
from app.modules.issues.infrastructure.models import IssueORM

SYNC_RISK_TITLE = "SYNC_RISK"


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

    def save(self, issue: IssueORM) -> None:
        self.session.add(issue)
