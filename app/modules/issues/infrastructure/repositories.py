from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.modules.doors.infrastructure.models import DoorORM
from app.modules.issues.domain.enums import IssueStatus, IssueWorkflowState
from app.modules.issues.infrastructure.models import IssueORM



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
        self, *, company_id: uuid.UUID, issue_id: uuid.UUID, for_update: bool = False
    ) -> IssueORM | None:
        query = (
            self.session.query(IssueORM)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.id == issue_id,
            )
        )
        if for_update:
            query = query.populate_existing().with_for_update()
        return query.one_or_none()

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
        include_closed: bool = False,
    ) -> list[IssueORM]:
        query = (
            self.session.query(IssueORM)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                DoorORM.project_id == project_id,
                DoorORM.installer_id == installer_id,
            )
        )
        if not include_closed:
            query = query.filter(IssueORM.status == IssueStatus.OPEN)
        return query.order_by(IssueORM.created_at.desc()).all()

    def list_by_projects_for_installer(
        self,
        *,
        company_id: uuid.UUID,
        project_ids: list[uuid.UUID],
        installer_id: uuid.UUID,
    ) -> list[tuple[IssueORM, uuid.UUID]]:
        """Open and closed issues of the installer's doors across projects, with the
        project id of each; one query for the cold sync snapshot."""
        if not project_ids:
            return []
        return (
            self.session.query(IssueORM, DoorORM.project_id)
            .join(DoorORM, DoorORM.id == IssueORM.door_id)
            .filter(
                IssueORM.company_id == company_id,
                DoorORM.project_id.in_(project_ids),
                DoorORM.installer_id == installer_id,
            )
            .order_by(IssueORM.created_at.desc())
            .all()
        )

    def list_created_by_user(
        self,
        *,
        company_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IssueORM]:
        return (
            self.session.query(IssueORM)
            .filter(
                IssueORM.company_id == company_id,
                IssueORM.created_by_user_id == created_by_user_id,
            )
            .order_by(IssueORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def save(self, issue: IssueORM) -> None:
        self.session.add(issue)
