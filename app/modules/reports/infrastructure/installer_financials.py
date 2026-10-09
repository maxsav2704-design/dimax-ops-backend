from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, Numeric, and_, case, cast, func, literal, null, or_, select, union_all
from sqlalchemy.orm import Session

from app.modules.addons.infrastructure.models import ProjectAddonFactORM, ProjectAddonPlanORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.ledger_queries import active_completed_work_filter
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.issues.domain.enums import IssueStatus
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.infrastructure.models import ProjectORM


def _metric_row(installer_id, project_id, **values):
    fields = {
        "installer_id": installer_id,
        "project_id": project_id,
        "revenue_total": cast(0, Numeric(12, 2)),
        "payroll_total": cast(0, Numeric(12, 2)),
        "installed_doors": literal(0),
        "addons_done_qty": cast(0, Numeric(12, 2)),
        "last_installed_at": cast(null(), DateTime(timezone=True)),
        "unrecorded_completed_works": literal(0),
        "missing_rates_installed_doors": literal(0),
        "missing_addon_plans_facts": literal(0),
        "missing_client_prices": literal(0),
    }
    fields.update(values)
    return select(*(value.label(name) for name, value in fields.items()))


def _work_rows(company_id: UUID):
    work, door, fact, plan = CompletedWorkORM, DoorORM, ProjectAddonFactORM, ProjectAddonPlanORM
    is_door = work.work_kind == "DOOR"
    client_revenue = case((is_door, door.our_price), else_=plan.client_price) * work.quantity
    movements = _metric_row(work.installer_id, work.project_id, payroll_total=work.amount_snapshot).where(
        work.company_id == company_id
    )
    # Performance belongs to the surviving ledger work, not today's assignee.
    # Client revenue keeps the reports' existing current client-price basis.
    completed = (
        _metric_row(
            work.installer_id, work.project_id,
            revenue_total=func.coalesce(client_revenue, 0),
            installed_doors=case((is_door, 1), else_=0),
            addons_done_qty=case((is_door, 0), else_=work.quantity),
            last_installed_at=case((is_door, work.completed_at), else_=None),
            missing_client_prices=case((client_revenue.is_(None), 1), else_=0),
            missing_addon_plans_facts=case((and_(~is_door, plan.id.is_(None)), 1), else_=0),
        )
        .select_from(work)
        .outerjoin(door, and_(door.company_id == company_id, door.id == work.door_id))
        .outerjoin(fact, and_(fact.company_id == company_id, fact.id == work.addon_fact_id))
        .outerjoin(plan, and_(plan.company_id == company_id, plan.project_id == work.project_id,
                             plan.addon_type_id == fact.addon_type_id))
        .where(active_completed_work_filter(company_id))
    )
    recorded_door = select(work.id).where(
        active_completed_work_filter(company_id), work.work_kind == "DOOR",
        work.project_id == door.project_id, work.door_id == door.id,
    ).exists()
    missing_doors = _metric_row(
        door.installer_id, door.project_id,
        unrecorded_completed_works=literal(1), missing_rates_installed_doors=literal(1),
    ).where(door.company_id == company_id, door.status == DoorStatus.INSTALLED, ~recorded_door)
    # A reversed addon fact is not an unrecorded new job.
    recorded_fact = select(work.id).where(
        work.company_id == company_id, work.work_kind == "ADDON",
        work.project_id == fact.project_id, work.addon_fact_id == fact.id,
    ).exists()
    missing_addons = _metric_row(
        fact.installer_id, fact.project_id, unrecorded_completed_works=literal(1),
    ).where(fact.company_id == company_id, ~recorded_fact)
    return union_all(movements, completed, missing_doors, missing_addons).subquery()


def installer_financial_matrix(session: Session, *, company_id: UUID, by_project: bool = False,
                               limit: int = 20, offset: int = 0, sort_by: str = "profit_total",
                               sort_dir: str = "desc") -> dict:
    raw = _work_rows(company_id)
    work_columns = [
        InstallerORM.id.label("installer_id"),
        func.count(func.distinct(case(
            (or_(raw.c.installed_doors > 0, raw.c.addons_done_qty > 0), ProjectORM.id), else_=None,
        ))).label("active_projects"),
        *(func.coalesce(func.sum(raw.c[name]), 0).label(name) for name in (
            "revenue_total", "payroll_total", "installed_doors", "addons_done_qty",
            "unrecorded_completed_works", "missing_rates_installed_doors",
            "missing_addon_plans_facts", "missing_client_prices",
        )),
        func.max(raw.c.last_installed_at).label("last_installed_at"),
    ]
    group = [InstallerORM.id]
    if by_project:
        work_columns.append(ProjectORM.id.label("project_id"))
        group.append(ProjectORM.id)
    work = (
        session.query(*work_columns).select_from(raw)
        .join(InstallerORM, and_(InstallerORM.id == raw.c.installer_id, InstallerORM.company_id == company_id))
        .outerjoin(ProjectORM, and_(ProjectORM.id == raw.c.project_id, ProjectORM.company_id == company_id))
        .group_by(*group)
        .having(or_(func.sum(raw.c.installed_doors) > 0, func.sum(raw.c.addons_done_qty) > 0,
                    func.sum(raw.c.payroll_total) != 0, func.sum(raw.c.unrecorded_completed_works) > 0))
        .subquery()
    )
    issue_columns = [DoorORM.installer_id.label("installer_id"), func.count(IssueORM.id).label("open_issues")]
    issue_group = [DoorORM.installer_id]
    if by_project:
        issue_columns.append(DoorORM.project_id.label("project_id"))
        issue_group.append(DoorORM.project_id)
    issues = (
        session.query(*issue_columns).select_from(IssueORM)
        .join(DoorORM, and_(DoorORM.id == IssueORM.door_id, DoorORM.company_id == company_id))
        .filter(IssueORM.company_id == company_id, IssueORM.status == IssueStatus.OPEN)
        .group_by(*issue_group).subquery()
    )
    profit = case(
        (work.c.unrecorded_completed_works + work.c.missing_client_prices > 0, None),
        else_=work.c.revenue_total - work.c.payroll_total,
    )
    margin = case((profit.is_(None), None),
                  (work.c.revenue_total > 0, profit * 100 / work.c.revenue_total), else_=0)
    average = case((profit.is_(None), None),
                   (work.c.installed_doors > 0, profit / work.c.installed_doors), else_=0)
    open_issues = func.coalesce(issues.c.open_issues, 0)
    columns = [work, InstallerORM.full_name.label("installer_name"),
               profit.label("profit_total"), margin.label("margin_pct"),
               average.label("avg_profit_per_door"), open_issues.label("open_issues")]
    if by_project:
        columns.append(ProjectORM.name.label("project_name"))
    issue_join = issues.c.installer_id == work.c.installer_id
    if by_project:
        issue_join = and_(issue_join, issues.c.project_id == work.c.project_id)
    query = session.query(*columns).select_from(work).join(InstallerORM, InstallerORM.id == work.c.installer_id)
    if by_project:
        query = query.outerjoin(ProjectORM, and_(ProjectORM.id == work.c.project_id, ProjectORM.company_id == company_id))
    query = query.outerjoin(issues, issue_join)
    counts = query.with_entities(func.count(), func.coalesce(func.sum(case((profit.is_(None), 1), else_=0)), 0)).one()
    unassigned = session.query(func.coalesce(func.sum(raw.c.unrecorded_completed_works), 0)).filter(
        raw.c.installer_id.is_(None)
    ).scalar()
    sort = {
        "profit_total": profit, "margin_pct": margin, "installed_doors": work.c.installed_doors,
        "avg_profit_per_door": average, "open_issues": open_issues,
    }.get(sort_by, profit)
    order = [(sort.asc() if sort_dir == "asc" else sort.desc()).nulls_last(), InstallerORM.full_name.asc(), InstallerORM.id.asc()]
    if by_project:
        order.extend([ProjectORM.name.asc().nulls_last(), ProjectORM.id.asc().nulls_last()])
    rows = query.order_by(*order).limit(limit).offset(offset).all()
    items = []
    for row in rows:
        amount = Decimal(row.profit_total) if row.profit_total is not None else None
        percentage = Decimal(row.margin_pct) if row.margin_pct is not None else None
        if amount is None:
            band = "INCOMPLETE"
        elif amount <= 0 or percentage < 15 or row.open_issues >= (3 if by_project else 5):
            band = "RISK"
        elif percentage >= (30 if by_project else 35) and amount >= (150 if by_project else 300) and row.open_issues <= (0 if by_project else 1):
            band = "STRONG"
        else:
            band = "WATCH"
        item = {
            "pricing_mode": "FACTORY", "installer_id": row.installer_id, "installer_name": row.installer_name,
            "performance_band": band, "installed_doors": int(row.installed_doors), "active_projects": int(row.active_projects),
            "open_issues": int(row.open_issues), "addons_done_qty": Decimal(row.addons_done_qty),
            "revenue_total": Decimal(row.revenue_total), "payroll_total": Decimal(row.payroll_total),
            "profit_total": amount, "margin_pct": round(float(percentage), 2) if percentage is not None else None,
            "avg_profit_per_door": Decimal(row.avg_profit_per_door) if row.avg_profit_per_door is not None else None,
            "unrecorded_completed_works": int(row.unrecorded_completed_works),
            "missing_rates_installed_doors": int(row.missing_rates_installed_doors),
            "missing_addon_plans_facts": int(row.missing_addon_plans_facts),
            "missing_client_prices": int(row.missing_client_prices), "last_installed_at": row.last_installed_at,
        }
        if by_project:
            item.update(project_id=row.project_id, project_name=row.project_name)
        items.append(item)
    return {"pricing_mode": "FACTORY", "total": int(counts[0]), "incomplete_items": int(counts[1]),
            "unassigned_completed_works": int(unassigned), "items": items}
