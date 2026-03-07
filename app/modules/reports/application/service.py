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
    def dispatcher_board(
        session: Session,
        *,
        company_id: uuid.UUID,
        now: datetime,
        projects_limit: int = 8,
        installers_limit: int = 8,
        recommendation_limit: int = 3,
    ) -> dict:
        return ReportsService._repo(session).dispatcher_board(
            company_id=company_id,
            now=now,
            projects_limit=projects_limit,
            installers_limit=installers_limit,
            recommendation_limit=recommendation_limit,
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
    def installers_kpi(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int = 200,
        offset: int = 0,
        sort_by: str = "installed_doors",
        sort_dir: str = "desc",
    ) -> list[dict]:
        return ReportsService._repo(session).installers_kpi(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    @staticmethod
    def installer_profitability_matrix(
        session: Session,
        *,
        company_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "profit_total",
        sort_dir: str = "desc",
    ) -> dict:
        return ReportsService._repo(session).installer_profitability_matrix(
            company_id=company_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    @staticmethod
    def installer_project_profitability(
        session: Session,
        *,
        company_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "profit_total",
        sort_dir: str = "desc",
    ) -> dict:
        return ReportsService._repo(session).installer_project_profitability(
            company_id=company_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    @staticmethod
    def risk_concentration(
        session: Session,
        *,
        company_id: uuid.UUID,
        limit: int = 5,
    ) -> dict:
        return ReportsService._repo(session).risk_concentration(
            company_id=company_id,
            limit=limit,
        )

    @staticmethod
    def installer_kpi_details(
        session: Session,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> dict:
        return ReportsService._repo(session).installer_kpi_details(
            company_id=company_id,
            installer_id=installer_id,
        )

    @staticmethod
    def order_numbers_kpi(
        session: Session,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID | None,
        q: str | None,
        limit: int = 200,
        offset: int = 0,
        sort_by: str = "total_doors",
        sort_dir: str = "desc",
    ) -> dict:
        return ReportsService._repo(session).order_numbers_kpi(
            company_id=company_id,
            project_id=project_id,
            q=q,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
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
    def project_plan_fact(
        session: Session,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> dict:
        return ReportsService._repo(session).project_plan_fact(
            company_id=company_id,
            project_id=project_id,
        )

    @staticmethod
    def project_risk_drilldown(
        session: Session,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        limit: int = 5,
    ) -> dict:
        return ReportsService._repo(session).project_risk_drilldown(
            company_id=company_id,
            project_id=project_id,
            limit=limit,
        )

    @staticmethod
    def projects_margin(
        session: Session,
        *,
        company_id: uuid.UUID,
        limit: int = 10,
        offset: int = 0,
        sort_by: str = "profit_total",
        sort_dir: str = "desc",
    ) -> dict:
        return ReportsService._repo(session).projects_margin(
            company_id=company_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    @staticmethod
    def issues_addons_impact(
        session: Session,
        *,
        company_id: uuid.UUID,
        limit: int = 10,
    ) -> dict:
        return ReportsService._repo(session).issues_addons_impact(
            company_id=company_id,
            limit=limit,
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

    @staticmethod
    def audit_catalog_changes(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        entity_type: str | None,
        action: str | None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        return ReportsService._repo(session).audit_catalog_changes(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            entity_type=entity_type,
            action=action,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def limit_alerts(
        session: Session,
        *,
        company_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        return ReportsService._repo(session).limit_alerts(
            company_id=company_id,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def audit_catalog_changes_export_rows(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        entity_type: str | None,
        action: str | None,
        limit: int = 5000,
    ) -> list[dict]:
        return ReportsService._repo(session).audit_catalog_changes_export_rows(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            entity_type=entity_type,
            action=action,
            limit=limit,
        )

    @staticmethod
    def audit_issue_changes(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        issue_id: uuid.UUID | None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        return ReportsService._repo(session).audit_issue_changes(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            issue_id=issue_id,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def audit_issue_changes_export_rows(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        issue_id: uuid.UUID | None,
        limit: int = 5000,
    ) -> list[dict]:
        return ReportsService._repo(session).audit_issue_changes_export_rows(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            issue_id=issue_id,
            limit=limit,
        )

    @staticmethod
    def audit_installer_rate_changes(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        rate_id: uuid.UUID | None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        return ReportsService._repo(session).audit_installer_rate_changes(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            rate_id=rate_id,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def audit_installer_rate_changes_export_rows(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        action: str | None,
        rate_id: uuid.UUID | None,
        limit: int = 5000,
    ) -> list[dict]:
        return ReportsService._repo(session).audit_installer_rate_changes_export_rows(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            action=action,
            rate_id=rate_id,
            limit=limit,
        )

    @staticmethod
    def operations_center(
        session: Session,
        *,
        company_id: uuid.UUID,
        now: datetime,
    ) -> dict:
        return ReportsService._repo(session).operations_center(
            company_id=company_id,
            now=now,
        )

    @staticmethod
    def operations_sla_history(
        session: Session,
        *,
        company_id: uuid.UUID,
        now: datetime,
        days: int,
    ) -> dict:
        return ReportsService._repo(session).operations_sla_history(
            company_id=company_id,
            now=now,
            days=days,
        )

    @staticmethod
    def issues_analytics(
        session: Session,
        *,
        company_id: uuid.UUID,
        now: datetime,
        days: int,
    ) -> dict:
        return ReportsService._repo(session).issues_analytics(
            company_id=company_id,
            now=now,
            days=days,
        )
