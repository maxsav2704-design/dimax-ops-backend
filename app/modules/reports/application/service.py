from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy.orm import Session

from app.modules.reports.infrastructure.repositories import ReportsRepository


class ReportsService:
    @staticmethod
    def _repo(session: Session) -> ReportsRepository:
        return ReportsRepository(session)

    @staticmethod
    def kpi(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> dict:
        return ReportsService._repo(session).kpi(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
        )

    @staticmethod
    def problem_projects(
        session: Session,
        *,
        company_id: uuid.UUID,
        limit: int = 50,
    ) -> list[dict]:
        return ReportsService._repo(session).problem_projects(
            company_id=company_id,
            limit=limit,
        )

    @staticmethod
    def top_reasons(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int = 10,
    ) -> list[dict]:
        return ReportsService._repo(session).top_reasons(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    @staticmethod
    def project_profit(
        session: Session,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> dict:
        return ReportsService._repo(session).project_profit(
            company_id=company_id,
            project_id=project_id,
            date_from=date_from,
            date_to=date_to,
        )

    @staticmethod
    def delivery_stats(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> dict:
        return ReportsService._repo(session).delivery_stats(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
        )
