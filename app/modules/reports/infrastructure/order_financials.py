from uuid import UUID

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import ClientPriceSnapshotORM, CompletedWorkORM
from app.modules.issues.domain.enums import IssueStatus
from app.modules.issues.infrastructure.models import IssueORM


def order_financials(session: Session, *, company_id: UUID, project_id: UUID | None,
                     q: str | None, effective_work, limit: int, offset: int,
                     sort_by: str, sort_dir: str) -> dict:
    # Order/project membership is current door metadata, not a ledger snapshot.
    order_number = func.nullif(func.trim(DoorORM.order_number), "")
    doors = session.query(
        DoorORM.id, order_number.label("order_number"), DoorORM.status, DoorORM.our_price,
    ).filter(DoorORM.company_id == company_id, order_number.isnot(None))
    if project_id is not None:
        doors = doors.filter(DoorORM.project_id == project_id)
    if q and q.strip():
        doors = doors.filter(order_number.icontains(q.strip(), autoescape=True))
    doors = doors.subquery()

    client_price = func.coalesce(ClientPriceSnapshotORM.final_client_rate, doors.c.our_price)
    active = (
        session.query(
            effective_work.c.door_id,
            func.count().label("recorded_installations"),
            func.sum(func.coalesce(client_price, 0)).label("revenue"),
            func.sum(case((client_price.is_(None), 1), else_=0)).label("missing_client_prices"),
        ).select_from(effective_work)
        .join(doors, doors.c.id == effective_work.c.door_id)
        .outerjoin(ClientPriceSnapshotORM, and_(
            ClientPriceSnapshotORM.company_id == company_id,
            ClientPriceSnapshotORM.completed_work_id == effective_work.c.snapshot_work_id,
        ))
        .group_by(effective_work.c.door_id).subquery()
    )
    # Aggregate each one-to-many relation before joining, so issues cannot multiply money.
    movements = (
        session.query(CompletedWorkORM.door_id, func.sum(CompletedWorkORM.amount_snapshot).label("payroll"))
        .join(doors, doors.c.id == CompletedWorkORM.door_id)
        .filter(CompletedWorkORM.company_id == company_id, CompletedWorkORM.work_kind == "DOOR")
        .group_by(CompletedWorkORM.door_id).subquery()
    )
    issues = (
        session.query(IssueORM.door_id, func.count().label("open_issues"))
        .join(doors, doors.c.id == IssueORM.door_id)
        .filter(IssueORM.company_id == company_id, IssueORM.status == IssueStatus.OPEN)
        .group_by(IssueORM.door_id).subquery()
    )
    installed = func.sum(case((doors.c.status == DoorStatus.INSTALLED, 1), else_=0))
    unrecorded = func.sum(case((and_(
        doors.c.status == DoorStatus.INSTALLED, active.c.door_id.is_(None),
    ), 1), else_=0))
    missing_client = func.sum(func.coalesce(active.c.missing_client_prices, 0))
    revenue = func.sum(func.coalesce(active.c.revenue, 0))
    payroll = func.sum(func.coalesce(movements.c.payroll, 0))
    grouped = (
        session.query(
            doors.c.order_number, func.count().label("total_doors"), installed.label("installed_doors"),
            func.sum(case((doors.c.status == DoorStatus.NOT_INSTALLED, 1), else_=0)).label("not_installed_doors"),
            func.sum(func.coalesce(issues.c.open_issues, 0)).label("open_issues"),
            func.sum(doors.c.our_price).label("planned_revenue_total"),
            revenue.label("installed_revenue_total"), payroll.label("payroll_total"),
            case((unrecorded + missing_client > 0, None), else_=revenue - payroll).label("profit_total"),
            unrecorded.label("unrecorded_completed_works"), unrecorded.label("missing_rates_installed_doors"),
            missing_client.label("missing_client_prices"),
            func.sum(func.coalesce(active.c.recorded_installations, 0)).label("recorded_installations"),
            (installed * 100.0 / func.count()).label("completion_pct"),
        ).select_from(doors)
        .outerjoin(active, active.c.door_id == doors.c.id)
        .outerjoin(movements, movements.c.door_id == doors.c.id)
        .outerjoin(issues, issues.c.door_id == doors.c.id)
        .group_by(doors.c.order_number).subquery()
    )
    coverage = session.query(
        func.count().label("total"),
        func.coalesce(func.sum(case((grouped.c.profit_total.is_(None), 1), else_=0)), 0).label("incomplete_orders"),
    ).select_from(grouped).one()
    allowed = {name: grouped.c[name] for name in (
        "order_number", "total_doors", "installed_doors", "not_installed_doors", "open_issues",
        "planned_revenue_total", "installed_revenue_total", "payroll_total", "profit_total", "completion_pct",
    )}
    sort = allowed.get(sort_by, grouped.c.total_doors)
    rows = session.query(grouped).order_by(
        (sort.asc() if sort_dir == "asc" else sort.desc()).nulls_last(), grouped.c.order_number.asc(),
    ).limit(limit).offset(offset).all()
    return {
        "pricing_mode": "FACTORY", "total": int(coverage.total),
        "incomplete_orders": int(coverage.incomplete_orders), "limit": limit, "offset": offset,
        "items": [{**dict(row._mapping), "pricing_mode": "FACTORY",
                   "completion_pct": round(float(row.completion_pct), 2)} for row in rows],
    }
