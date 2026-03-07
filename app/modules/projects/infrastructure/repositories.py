from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Integer, and_, case, cast, func, or_
from sqlalchemy.orm import Session

from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectImportRunORM, ProjectORM


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


class ProjectImportRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _errors_count_expr():
        errors_node = ProjectImportRunORM.result_payload["errors"]
        errors_count_node = ProjectImportRunORM.result_payload["errors_count"].astext
        return case(
            (
                func.jsonb_typeof(errors_node) == "array",
                func.jsonb_array_length(errors_node),
            ),
            else_=func.coalesce(cast(errors_count_node, Integer), 0),
        )

    def get_by_fingerprint(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        fingerprint: str,
        import_mode: str,
    ) -> ProjectImportRunORM | None:
        return (
            self.session.query(ProjectImportRunORM)
            .filter(
                ProjectImportRunORM.company_id == company_id,
                ProjectImportRunORM.project_id == project_id,
                ProjectImportRunORM.fingerprint == fingerprint,
                ProjectImportRunORM.import_mode == import_mode,
            )
            .order_by(ProjectImportRunORM.created_at.desc())
            .one_or_none()
        )

    def save(self, run: ProjectImportRunORM) -> None:
        self.session.add(run)

    def get_by_id(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> ProjectImportRunORM | None:
        return (
            self.session.query(ProjectImportRunORM)
            .filter(
                ProjectImportRunORM.company_id == company_id,
                ProjectImportRunORM.project_id == project_id,
                ProjectImportRunORM.id == run_id,
            )
            .one_or_none()
        )

    def list(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        import_mode: str | None,
        limit: int,
        offset: int,
    ) -> list[ProjectImportRunORM]:
        q = self.session.query(ProjectImportRunORM).filter(
            ProjectImportRunORM.company_id == company_id,
            ProjectImportRunORM.project_id == project_id,
        )
        if import_mode is not None:
            q = q.filter(ProjectImportRunORM.import_mode == import_mode)
        return (
            q.order_by(ProjectImportRunORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def latest_retryable_for_project(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> ProjectImportRunORM | None:
        return (
            self.session.query(ProjectImportRunORM)
            .filter(
                ProjectImportRunORM.company_id == company_id,
                ProjectImportRunORM.project_id == project_id,
                ProjectImportRunORM.import_mode.in_(["import", "import_retry"]),
            )
            .order_by(ProjectImportRunORM.created_at.desc())
            .first()
        )

    def list_by_ids(
        self,
        *,
        company_id: uuid.UUID,
        run_ids: list[uuid.UUID],
    ) -> list[ProjectImportRunORM]:
        if not run_ids:
            return []
        return (
            self.session.query(ProjectImportRunORM)
            .filter(
                ProjectImportRunORM.company_id == company_id,
                ProjectImportRunORM.id.in_(run_ids),
            )
            .all()
        )

    def failed_queue(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[ProjectImportRunORM, ProjectORM | None]], int]:
        errors_count_expr = self._errors_count_expr()
        q = (
            self.session.query(ProjectImportRunORM, ProjectORM)
            .outerjoin(
                ProjectORM,
                and_(
                    ProjectORM.id == ProjectImportRunORM.project_id,
                    ProjectORM.company_id == ProjectImportRunORM.company_id,
                ),
            )
            .filter(
                ProjectImportRunORM.company_id == company_id,
                ProjectImportRunORM.import_mode.in_(["import", "import_retry"]),
                errors_count_expr > 0,
            )
        )
        if project_id is not None:
            q = q.filter(ProjectImportRunORM.project_id == project_id)

        total = int(q.with_entities(func.count(ProjectImportRunORM.id)).scalar() or 0)
        rows = (
            q.order_by(ProjectImportRunORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return rows, total
