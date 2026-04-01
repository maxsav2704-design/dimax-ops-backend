from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, func, not_, or_, select

from app.modules.doors.infrastructure.models import DoorORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.earnings.api.installer_schemas import (
    InstallerEarningsByInstallTypeDTO,
    InstallerEarningsByProjectDTO,
    InstallerEarningsSummaryDTO,
    InstallerEarningsWeeklyBreakdownDTO,
)
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.projects.infrastructure.models import ProjectORM


def _period_bounds(period: str, anchor_date: date | None) -> tuple[datetime, datetime]:
    day = anchor_date or datetime.now(timezone.utc).date()
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    if period == "day":
        return start, start + timedelta(days=1)
    if period == "week":
        week_start = start - timedelta(days=start.weekday())
        return week_start, week_start + timedelta(days=7)
    if period == "month":
        month_start = start.replace(day=1)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        return month_start, next_month
    raise ValueError(f"Unsupported period: {period}")


class InstallerEarningsApiService:
    @staticmethod
    def summary(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        period: str,
        anchor_date: date | None,
    ) -> InstallerEarningsSummaryDTO:
        period_start, period_end = _period_bounds(period, anchor_date)

        reversed_ids = (
            select(CompletedWorkORM.correction_ref_id)
            .where(
                CompletedWorkORM.company_id == company_id,
                CompletedWorkORM.installer_id == installer_id,
                CompletedWorkORM.entry_type == "REVERSAL",
                CompletedWorkORM.correction_ref_id.is_not(None),
            )
        )

        rows = (
            uow.session.query(CompletedWorkORM)
            .filter(
                CompletedWorkORM.company_id == company_id,
                CompletedWorkORM.installer_id == installer_id,
                CompletedWorkORM.completed_at >= period_start,
                CompletedWorkORM.completed_at < period_end,
                or_(
                    and_(
                        CompletedWorkORM.entry_type == "ORIGINAL",
                        not_(CompletedWorkORM.id.in_(reversed_ids)),
                    ),
                    CompletedWorkORM.entry_type == "CORRECTION",
                ),
            )
            .all()
        )

        total = sum((Decimal(str(row.amount_snapshot or 0)) for row in rows), Decimal("0"))
        jobs_count = len(rows)

        by_install_type_rows = (
            uow.session.query(
                func.coalesce(DoorTypeORM.name, "Unknown"),
                func.coalesce(func.sum(CompletedWorkORM.amount_snapshot), 0),
            )
            .outerjoin(DoorORM, DoorORM.id == CompletedWorkORM.door_id)
            .outerjoin(DoorTypeORM, DoorTypeORM.id == DoorORM.door_type_id)
            .filter(
                CompletedWorkORM.company_id == company_id,
                CompletedWorkORM.installer_id == installer_id,
                CompletedWorkORM.completed_at >= period_start,
                CompletedWorkORM.completed_at < period_end,
                or_(
                    and_(
                        CompletedWorkORM.entry_type == "ORIGINAL",
                        not_(CompletedWorkORM.id.in_(reversed_ids)),
                    ),
                    CompletedWorkORM.entry_type == "CORRECTION",
                ),
            )
            .group_by(DoorTypeORM.name)
            .order_by(func.sum(CompletedWorkORM.amount_snapshot).desc())
            .all()
        )

        by_project_rows = (
            uow.session.query(
                CompletedWorkORM.project_id,
                func.coalesce(ProjectORM.name, "Unknown project"),
                func.coalesce(func.sum(CompletedWorkORM.amount_snapshot), 0),
            )
            .outerjoin(ProjectORM, ProjectORM.id == CompletedWorkORM.project_id)
            .filter(
                CompletedWorkORM.company_id == company_id,
                CompletedWorkORM.installer_id == installer_id,
                CompletedWorkORM.completed_at >= period_start,
                CompletedWorkORM.completed_at < period_end,
                or_(
                    and_(
                        CompletedWorkORM.entry_type == "ORIGINAL",
                        not_(CompletedWorkORM.id.in_(reversed_ids)),
                    ),
                    CompletedWorkORM.entry_type == "CORRECTION",
                ),
            )
            .group_by(CompletedWorkORM.project_id, ProjectORM.name)
            .order_by(func.sum(CompletedWorkORM.amount_snapshot).desc())
            .all()
        )

        weekly_breakdown: list[InstallerEarningsWeeklyBreakdownDTO] = []
        if period == "month":
            weekly_totals: dict[date, Decimal] = {}
            for row in rows:
                bucket = row.completed_at.date() - timedelta(days=row.completed_at.date().weekday())
                weekly_totals[bucket] = weekly_totals.get(bucket, Decimal("0")) + Decimal(
                    str(row.amount_snapshot or 0)
                )
            weekly_breakdown = [
                InstallerEarningsWeeklyBreakdownDTO(
                    week_start=bucket.isoformat(),
                    total=amount,
                )
                for bucket, amount in sorted(weekly_totals.items())
            ]

        return InstallerEarningsSummaryDTO(
            total=total,
            jobs_count=jobs_count,
            by_install_type=[
                InstallerEarningsByInstallTypeDTO(
                    install_type=str(name or "Unknown"),
                    total=Decimal(str(amount or 0)),
                )
                for name, amount in by_install_type_rows
            ],
            by_project=[
                InstallerEarningsByProjectDTO(
                    project_id=project_id,
                    project_name=str(project_name or "Unknown project"),
                    total=Decimal(str(amount or 0)),
                )
                for project_id, project_name, amount in by_project_rows
            ],
            weekly_breakdown=weekly_breakdown,
        )
