from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, *, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> ProjectORM | None:
        return (
            self.session.query(ProjectORM)
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.id == project_id,
                ProjectORM.deleted_at.is_(None),
            )
            .one_or_none()
        )

    def list(
        self,
        *,
        company_id: uuid.UUID,
        q: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProjectORM]:
        query = (
            self.session.query(ProjectORM)
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.deleted_at.is_(None),
            )
        )

        if status:
            query = query.filter(ProjectORM.status == status)

        if q:
            like = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    ProjectORM.name.ilike(like),
                    ProjectORM.address.ilike(like),
                )
            )

        return (
            query.order_by(ProjectORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def save(self, project: ProjectORM) -> None:
        self.session.add(project)

    def soft_delete(self, project: ProjectORM) -> None:
        project.deleted_at = datetime.now(timezone.utc)
        self.session.add(project)

    def list_by_ids(
        self,
        *,
        company_id: uuid.UUID,
        ids: list[uuid.UUID],
    ) -> list[ProjectORM]:
        if not ids:
            return []
        return (
            self.session.query(ProjectORM)
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.id.in_(ids),
                ProjectORM.deleted_at.is_(None),
            )
            .order_by(ProjectORM.created_at.desc())
            .all()
        )

    def mark_problem_bulk(
        self,
        *,
        company_id: uuid.UUID,
        project_ids: list[uuid.UUID],
        reason: str,
    ) -> list[uuid.UUID]:
        if not project_ids:
            return []
        rows = (
            self.session.query(ProjectORM)
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.id.in_(project_ids),
            )
            .all()
        )
        updated: list[uuid.UUID] = []
        for p in rows:
            if p.status != ProjectStatus.PROBLEM:
                p.status = ProjectStatus.PROBLEM
                updated.append(p.id)
        self.session.flush()
        return updated
