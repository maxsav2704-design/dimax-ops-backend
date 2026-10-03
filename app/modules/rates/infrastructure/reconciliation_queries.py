from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Numeric, String, and_, case, cast, exists, func, literal, null, or_, select, true, union_all
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM, ProjectAddonPlanORM, ProjectUrgencySurchargeORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.modules.rates.infrastructure.price_list_models import FactoryPriceListItemORM


def _source(source_type, kind, target_id, source_id, legacy_price, *, source_name=None,
            project_id=None, project_name=None, installer_id=None, installer_name=None,
            effective_from=None, quantity=None, uses_snapshot=None, uses_surcharge=None, source_available=None):
    return select(
        literal(source_type).label("source_type"), literal(kind).label("kind"),
        target_id.label("target_id"), source_id.label("source_id"),
        legacy_price.label("legacy_price"),
        (source_name if source_name is not None else cast(null(), String)).label("source_name"),
        (project_id if project_id is not None else cast(null(), PgUUID)).label("project_id"),
        (project_name if project_name is not None else cast(null(), String)).label("project_name"),
        (installer_id if installer_id is not None else cast(null(), PgUUID)).label("installer_id"),
        (installer_name if installer_name is not None else cast(null(), String)).label("installer_name"),
        (effective_from if effective_from is not None else cast(null(), DateTime(timezone=True))).label("effective_from"),
        (quantity if quantity is not None else cast(null(), Numeric(12, 2))).label("quantity"),
        (uses_snapshot if uses_snapshot is not None else literal(False)).label("uses_snapshot"),
        (uses_surcharge if uses_surcharge is not None else literal(False)).label("uses_surcharge"),
        (source_available if source_available is not None else literal(True)).label("source_available"),
    )


def reconciliation_query(*, company_id: UUID, price_list_id: UUID | None, at: datetime,
                         limit: int, offset: int, issues_only: bool, kind: str | None):
    rates, doors, plans = InstallerRateORM, DoorORM, ProjectAddonPlanORM
    installers, projects = InstallerORM, ProjectORM
    door_types, addons, lines = DoorTypeORM, AddonTypeORM, FactoryPriceListItemORM
    ranked = select(
        rates.id, rates.installer_id, rates.door_type_id, rates.price, rates.effective_from,
        func.row_number().over(partition_by=(rates.installer_id, rates.door_type_id),
                               order_by=rates.effective_from.desc()).label("rank"),
    ).where(rates.company_id == company_id, rates.effective_from <= at).cte("ranked_rates")
    current = select(ranked).where(ranked.c.rank == 1).cte("current_rates")
    installer_available = and_(installers.id.is_not(None), installers.deleted_at.is_(None), installers.is_active.is_(True))
    project_available = and_(projects.id.is_not(None), projects.deleted_at.is_(None))
    installer_join = and_(installers.company_id == company_id, installers.id == current.c.installer_id)

    rate_rows = _source("INSTALLER_RATE", "DOOR", current.c.door_type_id, current.c.id, current.c.price,
        source_name=installers.full_name, installer_id=current.c.installer_id, installer_name=installers.full_name,
        effective_from=current.c.effective_from, source_available=installer_available,
    ).select_from(current).outerjoin(installers, installer_join)
    future_rows = _source("SCHEDULED_RATE", "DOOR", rates.door_type_id, rates.id, rates.price,
        source_name=installers.full_name, installer_id=rates.installer_id, installer_name=installers.full_name,
        effective_from=rates.effective_from, source_available=installer_available,
    ).select_from(rates).outerjoin(installers, and_(installers.company_id == company_id, installers.id == rates.installer_id)
    ).where(rates.company_id == company_id, rates.effective_from > at)

    base_rate = func.coalesce(doors.installer_rate_snapshot, current.c.price)
    # Match completion.py: zero surcharge_pct currently falls back to 100 percent.
    multiplier = case((doors.surcharge_pct == 0, 100), else_=doors.surcharge_pct) / literal(100)
    door_rate = func.round(case((doors.apply_surcharge_to_installer.is_(True), base_rate * multiplier), else_=base_rate), 2)
    door_rows = _source("DOOR", "DOOR", doors.door_type_id, doors.id, door_rate,
        source_name=func.coalesce(doors.door_code, doors.unit_label), project_id=doors.project_id,
        project_name=projects.name, installer_id=doors.installer_id, installer_name=installers.full_name,
        uses_snapshot=doors.installer_rate_snapshot.is_not(None),
        uses_surcharge=and_(doors.apply_surcharge_to_installer.is_(True), doors.surcharge_pct.not_in((0, 100))),
        source_available=and_(project_available, or_(doors.installer_id.is_(None), installer_available)),
    ).select_from(doors).outerjoin(current, and_(current.c.installer_id == doors.installer_id,
        current.c.door_type_id == doors.door_type_id)
    ).outerjoin(projects, and_(projects.company_id == company_id, projects.id == doors.project_id)
    ).outerjoin(installers, and_(installers.company_id == company_id, installers.id == doors.installer_id)
    ).where(doors.company_id == company_id, doors.status != DoorStatus.INSTALLED)

    plan_rows = _source("ADDON_PLAN", "ADDON", plans.addon_type_id, plans.id, plans.installer_price,
        source_name=projects.name, project_id=plans.project_id, project_name=projects.name,
        source_available=project_available,
    ).select_from(plans).outerjoin(projects, and_(projects.company_id == company_id, projects.id == plans.project_id)
    ).where(plans.company_id == company_id)
    def in_price_list(work_kind, target):
        return exists(select(lines.id).where(lines.company_id == company_id,
            lines.price_list_id == price_list_id, lines.kind == work_kind,
            func.coalesce(lines.door_type_id, lines.addon_type_id) == target))
    default_rows = _source("ADDON_DEFAULT", "ADDON", addons.id, addons.id, addons.default_installer_price,
        source_name=addons.name,
    ).where(addons.company_id == company_id,
        or_(and_(addons.is_active.is_(True), addons.deleted_at.is_(None)), in_price_list("ADDON", addons.id)))

    facts = ProjectAddonFactORM
    unpaid_rows = _source("ADDON_FACT", "ADDON", facts.addon_type_id, facts.id, plans.installer_price,
        project_id=facts.project_id, project_name=projects.name, installer_id=facts.installer_id,
        installer_name=installers.full_name, effective_from=facts.done_at, quantity=facts.qty_done,
        source_available=and_(project_available, installer_available),
    ).select_from(facts).outerjoin(plans, and_(plans.company_id == company_id,
        plans.project_id == facts.project_id, plans.addon_type_id == facts.addon_type_id)
    ).outerjoin(projects, and_(projects.company_id == company_id, projects.id == facts.project_id)
    ).outerjoin(installers, and_(installers.company_id == company_id, installers.id == facts.installer_id)
    ).where(facts.company_id == company_id, ~exists(select(CompletedWorkORM.id).where(
        CompletedWorkORM.company_id == company_id, CompletedWorkORM.addon_fact_id == facts.id)))
    legacy = union_all(rate_rows, future_rows, door_rows, plan_rows, default_rows, unpaid_rows).cte("legacy_sources")
    empty_catalog = _source("CATALOG", "DOOR", door_types.id, door_types.id, cast(null(), Numeric(12, 2)),
        source_name=door_types.name,
    ).where(door_types.company_id == company_id,
        or_(and_(door_types.is_active.is_(True), door_types.deleted_at.is_(None)), in_price_list("DOOR", door_types.id)),
        ~exists(select(legacy.c.source_id).where(legacy.c.kind == "DOOR", legacy.c.target_id == door_types.id)))
    sources = union_all(select(legacy), empty_catalog).cte("sources")
    catalog = union_all(
        select(literal("DOOR").label("kind"), door_types.id.label("target_id"), door_types.name,
               literal("pcs").label("unit"), and_(door_types.is_active.is_(True), door_types.deleted_at.is_(None)).label("available")
        ).where(door_types.company_id == company_id),
        select(literal("ADDON"), addons.id, addons.name, addons.unit,
               and_(addons.is_active.is_(True), addons.deleted_at.is_(None))
        ).where(addons.company_id == company_id),
    ).cte("catalog")
    proposed = select(lines.kind, func.coalesce(lines.door_type_id, lines.addon_type_id).label("target_id"),
        lines.name, lines.unit, lines.installer_price).where(
        lines.company_id == company_id, lines.price_list_id == price_list_id,
    ).cte("proposed")
    variations = select(sources.c.kind, sources.c.target_id,
        func.count(func.distinct(sources.c.legacy_price)).label("legacy_variants")
    ).select_from(sources).join(catalog, and_(catalog.c.kind == sources.c.kind, catalog.c.target_id == sources.c.target_id)
    ).where(sources.c.source_type.in_(("INSTALLER_RATE", "DOOR", "ADDON_PLAN")),
        sources.c.source_available.is_(True), catalog.c.available.is_(True), sources.c.legacy_price > 0
    ).group_by(sources.c.kind, sources.c.target_id).cte("variations")
    variants = func.coalesce(variations.c.legacy_variants, 0)
    available = func.coalesce(catalog.c.available, False)
    unit_changed = and_(proposed.c.installer_price.is_not(None), catalog.c.target_id.is_not(None), proposed.c.unit != catalog.c.unit)
    changed = or_(~available, and_(proposed.c.installer_price.is_not(None),
                                  or_(proposed.c.name != catalog.c.name, proposed.c.unit != catalog.c.unit)))
    status = case(
        (or_(~sources.c.source_available, ~available), "UNAVAILABLE"),
        (unit_changed, "UNIT_CHANGED"),
        (proposed.c.installer_price.is_(None), "MISSING_PROPOSED"),
        (or_(sources.c.legacy_price.is_(None), sources.c.legacy_price <= 0), "MISSING_LEGACY"),
        (sources.c.legacy_price != proposed.c.installer_price, "DIFFERENT"), else_="MATCH",
    )
    report = select(
        *sources.c, func.coalesce(catalog.c.name, proposed.c.name, cast(sources.c.target_id, String)).label("name"),
        func.coalesce(catalog.c.unit, proposed.c.unit, case((sources.c.kind == "DOOR", "pcs"), else_="-")).label("unit"),
        proposed.c.name.label("proposed_name"), proposed.c.unit.label("proposed_unit"),
        proposed.c.installer_price.label("proposed_price"), variants.label("legacy_variants"),
        case((and_(available, ~unit_changed, sources.c.legacy_price > 0),
              proposed.c.installer_price - sources.c.legacy_price), else_=None).label("delta"),
        changed.label("catalog_changed"), status.label("status"),
        or_(status != "MATCH", changed, sources.c.uses_snapshot, sources.c.uses_surcharge,
            sources.c.source_type.in_(("SCHEDULED_RATE", "ADDON_FACT")),
            and_(variants > 1, sources.c.source_type.in_(("INSTALLER_RATE", "DOOR", "ADDON_PLAN")))).label("review_required"),
    ).select_from(sources).outerjoin(catalog, and_(catalog.c.kind == sources.c.kind, catalog.c.target_id == sources.c.target_id)
    ).outerjoin(proposed, and_(proposed.c.kind == sources.c.kind, proposed.c.target_id == sources.c.target_id)
    ).outerjoin(variations, and_(variations.c.kind == sources.c.kind, variations.c.target_id == sources.c.target_id)).cte("report")

    predicate = and_(report.c.review_required if issues_only else true(), report.c.kind == kind if kind else true())
    def count_if(condition):
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)
    summary = select(
        func.count().label("total_sources"), count_if(predicate).label("total"),
        count_if(report.c.review_required).label("review_sources"),
        *(count_if(report.c.status == value).label(label) for value, label in (
            ("MATCH", "matching"), ("DIFFERENT", "different"), ("MISSING_PROPOSED", "missing_proposed"),
            ("MISSING_LEGACY", "missing_legacy"), ("UNAVAILABLE", "unavailable"), ("UNIT_CHANGED", "unit_changed"))),
        count_if(report.c.source_type == "SCHEDULED_RATE").label("scheduled_rates"),
        count_if(report.c.uses_snapshot).label("door_snapshots"), count_if(report.c.uses_surcharge).label("door_surcharges"),
        count_if(report.c.catalog_changed).label("catalog_changes"),
        count_if(report.c.source_type == "ADDON_FACT").label("pending_addon_facts"),
        select(func.count()).select_from(variations).where(variations.c.legacy_variants > 1
        ).scalar_subquery().label("multiple_rate_types"),
        select(func.count()).select_from(ProjectUrgencySurchargeORM).where(
            ProjectUrgencySurchargeORM.company_id == company_id, ProjectUrgencySurchargeORM.installer_amount > 0,
        ).scalar_subquery().label("urgency_surcharges"),
        select(func.count()).select_from(CompletedWorkORM).where(CompletedWorkORM.company_id == company_id
        ).scalar_subquery().label("historical_entries"),
    ).select_from(report).subquery("summary")
    page = select(report).where(predicate).order_by(report.c.kind, report.c.name, report.c.target_id,
        report.c.source_type, report.c.source_id).limit(limit).offset(offset).subquery("page")
    # Counts and the page share one SQL statement/snapshot, including an empty page.
    return select(*summary.c, *page.c).select_from(summary.outerjoin(page, true())).order_by(
        page.c.kind, page.c.name, page.c.target_id, page.c.source_type, page.c.source_id)
