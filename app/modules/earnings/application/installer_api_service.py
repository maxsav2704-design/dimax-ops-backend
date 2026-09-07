from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, not_, or_, select

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.earnings.api.installer_schemas import (
    InstallerEarningsDayDTO,
    InstallerEarningsByInstallTypeDTO,
    InstallerEarningsByProjectDTO,
    InstallerEarningsInstallTypeSummaryDTO,
    InstallerEarningsRowDTO,
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


def _period_key(period: str, period_start: datetime, period_end: datetime) -> str:
    if period == "day":
        return period_start.date().isoformat()
    if period == "month":
        return period_start.strftime("%Y-%m")
    return f"{period_start.date().isoformat()}..{(period_end - timedelta(days=1)).date().isoformat()}"


def _money(value: Decimal) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class InstallerEarningsApiService:
    @staticmethod
    def _effective_rows(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> list[CompletedWorkORM]:
        reversed_ids = (
            select(CompletedWorkORM.correction_ref_id)
            .where(
                CompletedWorkORM.company_id == company_id,
                CompletedWorkORM.installer_id == installer_id,
                CompletedWorkORM.entry_type == "REVERSAL",
                CompletedWorkORM.correction_ref_id.is_not(None),
            )
        )
        corrected_ids = (
            select(CompletedWorkORM.correction_ref_id)
            .where(
                CompletedWorkORM.company_id == company_id,
                CompletedWorkORM.installer_id == installer_id,
                CompletedWorkORM.entry_type == "CORRECTION",
                CompletedWorkORM.correction_ref_id.is_not(None),
            )
        )
        return (
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
                    and_(
                        CompletedWorkORM.entry_type == "REVERSAL",
                        CompletedWorkORM.correction_ref_id.is_not(None),
                        not_(CompletedWorkORM.correction_ref_id.in_(corrected_ids)),
                    ),
                    CompletedWorkORM.entry_type == "CORRECTION",
                ),
            )
            .order_by(CompletedWorkORM.completed_at.desc(), CompletedWorkORM.id.desc())
            .all()
        )

    @staticmethod
    def total_for_range(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> Decimal:
        rows = InstallerEarningsApiService._effective_rows(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            period_start=period_start,
            period_end=period_end,
        )
        return _money(
            sum((Decimal(str(row.amount_snapshot or 0)) for row in rows), Decimal("0"))
        )

    @staticmethod
    def _lookup_context(
        uow,
        *,
        company_id: uuid.UUID,
        rows: list[CompletedWorkORM],
    ) -> tuple[
        dict[uuid.UUID, tuple[DoorORM, DoorTypeORM | None]],
        dict[uuid.UUID, tuple[ProjectAddonFactORM, AddonTypeORM | None]],
        dict[uuid.UUID, ProjectORM],
    ]:
        door_ids = {row.door_id for row in rows if row.door_id is not None}
        addon_fact_ids = {
            row.addon_fact_id for row in rows if row.addon_fact_id is not None
        }
        project_ids = {row.project_id for row in rows if row.project_id is not None}

        door_map: dict[uuid.UUID, tuple[DoorORM, DoorTypeORM | None]] = {}
        if door_ids:
            door_rows = (
                uow.session.query(DoorORM, DoorTypeORM)
                .outerjoin(DoorTypeORM, DoorTypeORM.id == DoorORM.door_type_id)
                .filter(
                    DoorORM.company_id == company_id,
                    DoorORM.id.in_(door_ids),
                )
                .all()
            )
            door_map = {door.id: (door, door_type) for door, door_type in door_rows}

        addon_map: dict[uuid.UUID, tuple[ProjectAddonFactORM, AddonTypeORM | None]] = {}
        if addon_fact_ids:
            addon_rows = (
                uow.session.query(ProjectAddonFactORM, AddonTypeORM)
                .outerjoin(
                    AddonTypeORM,
                    and_(
                        AddonTypeORM.company_id == ProjectAddonFactORM.company_id,
                        AddonTypeORM.id == ProjectAddonFactORM.addon_type_id,
                    ),
                )
                .filter(
                    ProjectAddonFactORM.company_id == company_id,
                    ProjectAddonFactORM.id.in_(addon_fact_ids),
                )
                .all()
            )
            addon_map = {
                fact.id: (fact, addon_type) for fact, addon_type in addon_rows
            }

        project_map: dict[uuid.UUID, ProjectORM] = {}
        if project_ids:
            projects = (
                uow.session.query(ProjectORM)
                .filter(
                    ProjectORM.company_id == company_id,
                    ProjectORM.id.in_(project_ids),
                )
                .all()
            )
            project_map = {project.id: project for project in projects}

        return door_map, addon_map, project_map

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
        today_start, today_end = _period_bounds("day", anchor_date)
        month_start, month_end = _period_bounds("month", anchor_date)

        rows = InstallerEarningsApiService._effective_rows(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            period_start=period_start,
            period_end=period_end,
        )
        today_rows = InstallerEarningsApiService._effective_rows(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            period_start=today_start,
            period_end=today_end,
        )
        month_rows = InstallerEarningsApiService._effective_rows(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            period_start=month_start,
            period_end=month_end,
        )

        total = _money(
            sum((Decimal(str(row.amount_snapshot or 0)) for row in rows), Decimal("0"))
        )
        today_total = _money(
            sum((Decimal(str(row.amount_snapshot or 0)) for row in today_rows), Decimal("0"))
        )
        month_total = _money(
            sum((Decimal(str(row.amount_snapshot or 0)) for row in month_rows), Decimal("0"))
        )
        jobs_count = len(rows)

        door_map, addon_map, project_map = InstallerEarningsApiService._lookup_context(
            uow, company_id=company_id, rows=rows
        )
        by_type: dict[str, dict] = {}
        by_project: dict[str, dict] = {}
        by_day: dict[str, dict] = {}
        row_dtos: list[InstallerEarningsRowDTO] = []

        for row in rows:
            amount = _money(Decimal(str(row.amount_snapshot or 0)))
            quantity = Decimal(str(row.quantity or 0))
            door, door_type = door_map.get(row.door_id, (None, None)) if row.door_id else (None, None)
            addon_fact, addon_type = (
                addon_map.get(row.addon_fact_id, (None, None))
                if row.addon_fact_id
                else (None, None)
            )
            project = project_map.get(row.project_id) if row.project_id else None
            work_kind = str(getattr(row, "work_kind", None) or "DOOR")
            if work_kind == "ADDON":
                install_type_code = f"addon:{getattr(addon_fact, 'addon_type_id', 'unknown')}"
                install_type_label = str(
                    getattr(addon_type, "name", None) or "Additional work"
                )
                door_label = install_type_label
            else:
                install_type_code = str(getattr(door_type, "code", None) or "unknown")
                install_type_label = str(getattr(door_type, "name", None) or "Unknown")
                door_label = getattr(door, "unit_label", None) if door else None
            project_key = str(row.project_id) if row.project_id else "none"
            day_key = row.completed_at.date().isoformat()

            type_bucket = by_type.setdefault(
                install_type_code,
                {
                    "code": install_type_code,
                    "label": install_type_label,
                    "amount": Decimal("0"),
                    "quantity": 0,
                },
            )
            type_bucket["amount"] += amount
            type_bucket["quantity"] += int(quantity)

            project_bucket = by_project.setdefault(
                project_key,
                {
                    "project_id": row.project_id,
                    "project_name": getattr(project, "name", None) or "Unknown project",
                    "amount": Decimal("0"),
                },
            )
            project_bucket["amount"] += amount

            day_bucket = by_day.setdefault(
                day_key,
                {"date": day_key, "amount": Decimal("0"), "jobs_count": 0},
            )
            day_bucket["amount"] += amount
            day_bucket["jobs_count"] += 1

            row_dtos.append(
                InstallerEarningsRowDTO(
                    id=row.id,
                    work_date=day_key,
                    project_id=row.project_id,
                    project_name=getattr(project, "name", None) if project else None,
                    door_label=door_label,
                    install_type_code=install_type_code,
                    install_type_label=install_type_label,
                    quantity=quantity,
                    rate=_money(Decimal(str(row.rate_snapshot or 0))),
                    amount=amount,
                )
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
                    total=_money(amount),
                )
                for bucket, amount in sorted(weekly_totals.items())
            ]

        day_dtos = [
            InstallerEarningsDayDTO(
                date=item["date"],
                amount=_money(item["amount"]),
                jobs_count=int(item["jobs_count"]),
            )
            for item in sorted(by_day.values(), key=lambda item: item["date"], reverse=True)
        ]
        install_type_dtos = [
            InstallerEarningsInstallTypeSummaryDTO(
                code=item["code"],
                label=item["label"],
                amount=_money(item["amount"]),
                quantity=int(item["quantity"]),
            )
            for item in sorted(by_type.values(), key=lambda item: item["amount"], reverse=True)
        ]

        return InstallerEarningsSummaryDTO(
            total=total,
            jobs_count=jobs_count,
            by_install_type=[
                InstallerEarningsByInstallTypeDTO(
                    install_type=item["label"],
                    total=_money(item["amount"]),
                    amount=_money(item["amount"]),
                )
                for item in sorted(by_type.values(), key=lambda item: item["amount"], reverse=True)
            ],
            by_project=[
                InstallerEarningsByProjectDTO(
                    project_id=item["project_id"],
                    project_name=item["project_name"],
                    total=_money(item["amount"]),
                    amount=_money(item["amount"]),
                )
                for item in sorted(by_project.values(), key=lambda item: item["amount"], reverse=True)
            ],
            weekly_breakdown=weekly_breakdown,
            currency="ILS",
            today_total=today_total,
            month_total=month_total,
            by_day=day_dtos,
            period_key=_period_key(period, period_start, period_end),
            days=day_dtos,
            install_types=install_type_dtos,
            rows=row_dtos,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
