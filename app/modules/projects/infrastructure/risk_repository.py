from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.modules.projects.infrastructure.risk_models import RISK_KINDS, ProjectRiskORM


class ProjectRiskRepository:
    """One row per (project, kind): opened and closed by the system, read by the
    office. Idempotent: re-opening an open risk only refreshes its details."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _get(self, *, company_id: uuid.UUID, project_id: uuid.UUID, kind: str) -> ProjectRiskORM | None:
        return (
            self.session.query(ProjectRiskORM)
            .filter(
                ProjectRiskORM.company_id == company_id,
                ProjectRiskORM.project_id == project_id,
                ProjectRiskORM.kind == kind,
            )
            .one_or_none()
        )

    def open_risk(
        self, *, company_id: uuid.UUID, project_id: uuid.UUID, kind: str, details: str | None = None,
    ) -> tuple[uuid.UUID, bool]:
        """Returns (risk id, changed): changed is True only when the risk went from
        absent / closed to open."""
        if kind not in RISK_KINDS:
            raise ValueError(f"Unknown project risk kind: {kind}")
        text = (details or "")[:2000] or None
        row = self._get(company_id=company_id, project_id=project_id, kind=kind)
        now = datetime.now(timezone.utc)
        if row is None:
            row = ProjectRiskORM(
                company_id=company_id, project_id=project_id, kind=kind,
                status="OPEN", details=text, opened_at=now, closed_at=None,
            )
            self.session.add(row)
            self.session.flush()
            return row.id, True
        if row.status == "OPEN":
            if text is not None and text != row.details:
                row.details = text
                self.session.flush()
            return row.id, False
        row.status = "OPEN"
        row.details = text
        row.opened_at = now
        row.closed_at = None
        self.session.flush()
        return row.id, True

    def close_risk(self, *, company_id: uuid.UUID, project_id: uuid.UUID, kind: str) -> tuple[uuid.UUID | None, bool]:
        row = self._get(company_id=company_id, project_id=project_id, kind=kind)
        if row is None or row.status != "OPEN":
            return (row.id if row is not None else None), False
        row.status = "CLOSED"
        row.closed_at = datetime.now(timezone.utc)
        self.session.flush()
        return row.id, True

    def list_open_by_project(self, *, company_id: uuid.UUID, project_id: uuid.UUID) -> list[ProjectRiskORM]:
        return (
            self.session.query(ProjectRiskORM)
            .filter(
                ProjectRiskORM.company_id == company_id,
                ProjectRiskORM.project_id == project_id,
                ProjectRiskORM.status == "OPEN",
            )
            .order_by(ProjectRiskORM.kind.asc())
            .all()
        )

    def open_project_ids(self, *, company_id: uuid.UUID) -> set[uuid.UUID]:
        rows = (
            self.session.query(ProjectRiskORM.project_id)
            .filter(ProjectRiskORM.company_id == company_id, ProjectRiskORM.status == "OPEN")
            .distinct()
            .all()
        )
        return {row[0] for row in rows}
