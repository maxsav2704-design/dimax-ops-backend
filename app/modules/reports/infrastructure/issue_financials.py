from sqlalchemy import and_, case, func, or_

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.issues.domain.enums import IssueStatus, IssueWorkflowState
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.reasons.infrastructure.models import ReasonORM
from app.modules.reports.infrastructure.financial_sql import complete_sum


def issue_exposure(session, *, company_id, rate, factory_mode, limit):
    total = complete_sum if factory_mode else lambda value: func.coalesce(func.sum(value), 0)
    missing = case((rate.is_(None), 1), else_=0)
    profit = DoorORM.our_price - rate
    blocked = IssueORM.workflow_state == IssueWorkflowState.BLOCKED
    issues = session.query(
        func.count().label("open_issues"),
        func.coalesce(func.sum(case((blocked, 1), else_=0)), 0).label("blocked_open_issues"),
        total(DoorORM.our_price).label("open_issue_revenue_at_risk"),
        total(rate).label("open_issue_payroll_at_risk"),
        total(profit).label("open_issue_profit_at_risk"),
        total(case((blocked, profit), else_=0)).label("blocked_issue_profit_at_risk"),
        func.coalesce(func.sum(missing), 0).label("unpriced_open_issue_doors"),
        func.coalesce(func.sum(case((blocked, missing), else_=0)), 0).label("unpriced_blocked_issue_doors"),
    ).select_from(IssueORM).join(DoorORM, and_(
        DoorORM.id == IssueORM.door_id, DoorORM.company_id == company_id,
    )).filter(IssueORM.company_id == company_id, IssueORM.status == IssueStatus.OPEN)
    # Legacy rates are supplied as a correlated scalar expression, not a multiplying join.
    issue_row = issues.one()
    delayed = session.query(DoorORM).filter(
        DoorORM.company_id == company_id, DoorORM.status == DoorStatus.NOT_INSTALLED,
    )
    delayed_row = delayed.with_entities(
        func.count().label("not_installed_doors"),
        total(DoorORM.our_price).label("delayed_revenue_total"),
        total(rate).label("delayed_payroll_total"), total(profit).label("delayed_profit_total"),
        func.coalesce(func.sum(missing), 0).label("unpriced_delayed_doors"),
    ).one()
    reason_name = func.coalesce(ReasonORM.name, "No reason")
    reasons = delayed.outerjoin(ReasonORM, and_(
        ReasonORM.id == DoorORM.reason_id, ReasonORM.company_id == company_id,
    )).with_entities(
        ReasonORM.id.label("reason_id"), reason_name.label("reason_name"),
        func.count().label("doors"), total(DoorORM.our_price).label("revenue_delayed_total"),
        total(rate).label("payroll_delayed_total"), total(profit).label("profit_delayed_total"),
        func.coalesce(func.sum(missing), 0).label("unpriced_doors"),
    ).group_by(ReasonORM.id, reason_name)
    reason_count = reasons.count()
    rows = reasons.order_by(total(profit).desc().nulls_last(), func.count().desc(),
                            reason_name.asc(), ReasonORM.id.asc().nulls_last()).limit(limit).all()
    # The two populations overlap. An EXISTS condition values each door once.
    open_issue = session.query(IssueORM.id).filter(
        IssueORM.company_id == company_id, IssueORM.door_id == DoorORM.id,
        IssueORM.status == IssueStatus.OPEN,
    ).exists()
    exposure = session.query(
        total(profit).label("exposure_profit_total"), func.count().label("exposure_doors"),
        func.coalesce(func.sum(missing), 0).label("unpriced_exposure_doors"),
    ).select_from(DoorORM).filter(
        DoorORM.company_id == company_id, or_(DoorORM.status == DoorStatus.NOT_INSTALLED, open_issue),
    ).one()
    return {
        "summary": {**dict(issue_row._mapping), **dict(delayed_row._mapping),
                    **dict(exposure._mapping), "reason_rows_total": reason_count},
        "top_reasons": [{**dict(row._mapping), "pricing_mode": "FACTORY" if factory_mode else "LEGACY"} for row in rows],
    }
