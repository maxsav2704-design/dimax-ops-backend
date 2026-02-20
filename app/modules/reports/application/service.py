from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.outbox.domain.enums import (
    DeliveryStatus,
    OutboxChannel,
    OutboxStatus,
)
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.addons.infrastructure.models import (
    ProjectAddonFactORM,
    ProjectAddonPlanORM,
)
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.modules.reasons.infrastructure.models import ReasonORM


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


class ReportsService:
    @staticmethod
    def kpi(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> dict:
        installed_filter = [DoorORM.status == DoorStatus.INSTALLED]
        if date_from is not None:
            installed_filter.append(DoorORM.installed_at >= date_from)
        if date_to is not None:
            installed_filter.append(DoorORM.installed_at < date_to)

        installed_doors = (
            session.query(func.count(DoorORM.id))
            .filter(DoorORM.company_id == company_id, *installed_filter)
            .scalar()
        ) or 0

        not_installed_doors = (
            session.query(func.count(DoorORM.id))
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.status == DoorStatus.NOT_INSTALLED,
            )
            .scalar()
        ) or 0

        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )

        q_money = (
            session.query(
                func.coalesce(func.sum(DoorORM.our_price), 0).label("revenue"),
                func.coalesce(func.sum(InstallerRateORM.price), 0).label("payroll"),
                func.coalesce(
                    func.sum(
                        DoorORM.our_price - func.coalesce(InstallerRateORM.price, 0)
                    ),
                    0,
                ).label("profit"),
                func.coalesce(
                    func.sum(
                        case(
                            (InstallerRateORM.id.is_(None), 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing_rates"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(DoorORM.company_id == company_id, *installed_filter)
        )

        row = q_money.one()
        revenue_total = _dec(row.revenue)
        payroll_total = _dec(row.payroll)
        profit_total = _dec(row.profit)
        missing_rates = int(row.missing_rates or 0)

        addon_filter = [ProjectAddonFactORM.company_id == company_id]
        if date_from is not None:
            addon_filter.append(ProjectAddonFactORM.done_at >= date_from)
        if date_to is not None:
            addon_filter.append(ProjectAddonFactORM.done_at < date_to)

        plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id
            == ProjectAddonFactORM.addon_type_id,
        )

        addon_row = (
            session.query(
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(
                            ProjectAddonPlanORM.client_price, 0
                        )
                    ),
                    0,
                ).label("addon_revenue"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(
                            ProjectAddonPlanORM.installer_price, 0
                        )
                    ),
                    0,
                ).label("addon_payroll"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * (
                            func.coalesce(
                                ProjectAddonPlanORM.client_price, 0
                            )
                            - func.coalesce(
                                ProjectAddonPlanORM.installer_price, 0
                            )
                        )
                    ),
                    0,
                ).label("addon_profit"),
                func.coalesce(
                    func.sum(
                        case(
                            (ProjectAddonPlanORM.id.is_(None), 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("addon_missing_plan"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, plan_join)
            .filter(*addon_filter)
            .one()
        )

        revenue_total += _dec(addon_row.addon_revenue)
        payroll_total += _dec(addon_row.addon_payroll)
        profit_total += _dec(addon_row.addon_profit)
        addon_missing_plan = int(addon_row.addon_missing_plan or 0)

        problem_projects = (
            session.query(func.count(ProjectORM.id))
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.deleted_at.is_(None),
                ProjectORM.status == ProjectStatus.PROBLEM,
            )
            .scalar()
        ) or 0

        return {
            "installed_doors": int(installed_doors),
            "not_installed_doors": int(not_installed_doors),
            "revenue_total": revenue_total,
            "payroll_total": payroll_total,
            "profit_total": profit_total,
            "problem_projects": int(problem_projects),
            "missing_rates_installed_doors": missing_rates,
            "missing_addon_plans_done": addon_missing_plan,
        }

    @staticmethod
    def problem_projects(
        session: Session, *, company_id: uuid.UUID, limit: int = 50
    ) -> list[dict]:
        sub = (
            session.query(
                DoorORM.project_id.label("project_id"),
                func.count(DoorORM.id).label("not_installed_doors"),
            )
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.status == DoorStatus.NOT_INSTALLED,
            )
            .group_by(DoorORM.project_id)
            .subquery()
        )

        rows = (
            session.query(
                ProjectORM.id,
                ProjectORM.name,
                ProjectORM.address,
                func.coalesce(sub.c.not_installed_doors, 0).label(
                    "not_installed_doors"
                ),
            )
            .outerjoin(sub, sub.c.project_id == ProjectORM.id)
            .filter(
                ProjectORM.company_id == company_id,
                ProjectORM.deleted_at.is_(None),
            )
            .filter(func.coalesce(sub.c.not_installed_doors, 0) > 0)
            .order_by(
                func.coalesce(sub.c.not_installed_doors, 0).desc(),
                ProjectORM.created_at.desc(),
            )
            .limit(limit)
            .all()
        )

        return [
            {
                "project_id": r.id,
                "name": r.name,
                "address": r.address,
                "not_installed_doors": int(r.not_installed_doors),
            }
            for r in rows
        ]

    @staticmethod
    def top_reasons(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int = 10,
    ) -> list[dict]:
        rows = (
            session.query(
                DoorORM.reason_id.label("reason_id"),
                func.count(DoorORM.id).label("cnt"),
            )
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.status == DoorStatus.NOT_INSTALLED,
            )
            .group_by(DoorORM.reason_id)
            .order_by(func.count(DoorORM.id).desc())
            .limit(limit)
            .all()
        )

        reason_ids = [r.reason_id for r in rows if r.reason_id is not None]
        names = {}
        if reason_ids:
            rr = (
                session.query(ReasonORM.id, ReasonORM.name)
                .filter(
                    ReasonORM.company_id == company_id,
                    ReasonORM.id.in_(reason_ids),
                )
                .all()
            )
            names = {x.id: x.name for x in rr}

        result = []
        for r in rows:
            rid = r.reason_id
            result.append(
                {
                    "reason_id": rid,
                    "reason_name": (
                        names.get(rid, "No reason") if rid else "No reason"
                    ),
                    "count": int(r.cnt),
                }
            )
        return result

    @staticmethod
    def project_profit(
        session: Session,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> dict:
        installed_filter = [
            DoorORM.status == DoorStatus.INSTALLED,
            DoorORM.project_id == project_id,
        ]
        if date_from is not None:
            installed_filter.append(DoorORM.installed_at >= date_from)
        if date_to is not None:
            installed_filter.append(DoorORM.installed_at < date_to)

        rate_join = and_(
            InstallerRateORM.company_id == DoorORM.company_id,
            InstallerRateORM.installer_id == DoorORM.installer_id,
            InstallerRateORM.door_type_id == DoorORM.door_type_id,
        )

        row = (
            session.query(
                func.count(DoorORM.id).label("installed_doors"),
                func.coalesce(func.sum(DoorORM.our_price), 0).label("revenue"),
                func.coalesce(func.sum(InstallerRateORM.price), 0).label(
                    "payroll"
                ),
                func.coalesce(
                    func.sum(
                        DoorORM.our_price
                        - func.coalesce(InstallerRateORM.price, 0)
                    ),
                    0,
                ).label("profit"),
                func.coalesce(
                    func.sum(
                        case(
                            (InstallerRateORM.id.is_(None), 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing_rates"),
            )
            .select_from(DoorORM)
            .outerjoin(InstallerRateORM, rate_join)
            .filter(DoorORM.company_id == company_id, *installed_filter)
            .one()
        )

        door_revenue = _dec(row.revenue)
        door_payroll = _dec(row.payroll)
        door_profit = _dec(row.profit)

        addon_filter = [
            ProjectAddonFactORM.company_id == company_id,
            ProjectAddonFactORM.project_id == project_id,
        ]
        if date_from is not None:
            addon_filter.append(ProjectAddonFactORM.done_at >= date_from)
        if date_to is not None:
            addon_filter.append(ProjectAddonFactORM.done_at < date_to)

        plan_join = and_(
            ProjectAddonPlanORM.company_id == ProjectAddonFactORM.company_id,
            ProjectAddonPlanORM.project_id == ProjectAddonFactORM.project_id,
            ProjectAddonPlanORM.addon_type_id
            == ProjectAddonFactORM.addon_type_id,
        )

        addon_row = (
            session.query(
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(
                            ProjectAddonPlanORM.client_price, 0
                        )
                    ),
                    0,
                ).label("addon_revenue"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * func.coalesce(
                            ProjectAddonPlanORM.installer_price, 0
                        )
                    ),
                    0,
                ).label("addon_payroll"),
                func.coalesce(
                    func.sum(
                        ProjectAddonFactORM.qty_done
                        * (
                            func.coalesce(
                                ProjectAddonPlanORM.client_price, 0
                            )
                            - func.coalesce(
                                ProjectAddonPlanORM.installer_price, 0
                            )
                        )
                    ),
                    0,
                ).label("addon_profit"),
                func.coalesce(
                    func.sum(
                        case(
                            (ProjectAddonPlanORM.id.is_(None), 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("addon_missing_plan"),
            )
            .select_from(ProjectAddonFactORM)
            .outerjoin(ProjectAddonPlanORM, plan_join)
            .filter(*addon_filter)
            .one()
        )

        revenue_total = door_revenue + _dec(addon_row.addon_revenue)
        payroll_total = door_payroll + _dec(addon_row.addon_payroll)
        profit_total = door_profit + _dec(addon_row.addon_profit)

        return {
            "installed_doors": int(row.installed_doors or 0),
            "revenue_total": revenue_total,
            "payroll_total": payroll_total,
            "profit_total": profit_total,
            "missing_rates_installed_doors": int(row.missing_rates or 0),
        }

    @staticmethod
    def delivery_stats(
        session: Session,
        *,
        company_id: uuid.UUID,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> dict:
        q = session.query(OutboxMessageORM).filter(
            OutboxMessageORM.company_id == company_id
        )
        if date_from is not None:
            q = q.filter(OutboxMessageORM.created_at >= date_from)
        if date_to is not None:
            q = q.filter(OutboxMessageORM.created_at < date_to)

        wa = q.filter(OutboxMessageORM.channel == OutboxChannel.WHATSAPP)
        whatsapp_pending = (
            wa.filter(
                OutboxMessageORM.delivery_status == DeliveryStatus.PENDING
            ).count()
        )
        whatsapp_delivered = (
            wa.filter(
                OutboxMessageORM.delivery_status == DeliveryStatus.DELIVERED
            ).count()
        )
        whatsapp_failed = (
            wa.filter(
                OutboxMessageORM.delivery_status == DeliveryStatus.FAILED
            ).count()
        )

        em = q.filter(OutboxMessageORM.channel == OutboxChannel.EMAIL)
        email_sent = em.filter(
            OutboxMessageORM.status == OutboxStatus.SENT
        ).count()
        email_failed = em.filter(
            OutboxMessageORM.status == OutboxStatus.FAILED
        ).count()

        return {
            "whatsapp_pending": whatsapp_pending,
            "whatsapp_delivered": whatsapp_delivered,
            "whatsapp_failed": whatsapp_failed,
            "email_sent": email_sent,
            "email_failed": email_failed,
        }
