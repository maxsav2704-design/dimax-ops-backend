from sqlalchemy import and_, exists, literal, select, union, union_all

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM, ProjectAddonPlanORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.price_list_models import FactoryPriceListItemORM


def required_work_query(company_id, price_list_id):
    doors, addons, projects = DoorTypeORM, AddonTypeORM, ProjectORM
    catalog = union_all(
        select(literal("DOOR").label("kind"), doors.id.label("target_id"), doors.name,
               literal("pcs").label("unit"), and_(doors.is_active.is_(True), doors.deleted_at.is_(None)).label("available")
        ).where(doors.company_id == company_id),
        select(literal("ADDON"), addons.id, addons.name, addons.unit,
               and_(addons.is_active.is_(True), addons.deleted_at.is_(None))
        ).where(addons.company_id == company_id),
    ).cte("application_catalog")
    facts, plans, items = ProjectAddonFactORM, ProjectAddonPlanORM, FactoryPriceListItemORM
    required = union(
        select(catalog.c.kind, catalog.c.target_id).where(catalog.c.available.is_(True)),
        select(literal("DOOR"), DoorORM.door_type_id).join(projects, and_(
            projects.id == DoorORM.project_id, projects.company_id == company_id, projects.deleted_at.is_(None)
        )).where(DoorORM.company_id == company_id, DoorORM.status != DoorStatus.INSTALLED),
        select(literal("ADDON"), plans.addon_type_id).join(projects, and_(
            projects.id == plans.project_id, projects.company_id == company_id, projects.deleted_at.is_(None)
        )).where(plans.company_id == company_id),
        select(literal("ADDON"), facts.addon_type_id).join(projects, and_(
            projects.id == facts.project_id, projects.company_id == company_id, projects.deleted_at.is_(None)
        )).where(facts.company_id == company_id, ~exists(select(CompletedWorkORM.id).where(
            CompletedWorkORM.company_id == company_id, CompletedWorkORM.addon_fact_id == facts.id))),
        select(items.kind, items.door_type_id).where(items.company_id == company_id,
            items.price_list_id == price_list_id, items.kind == "DOOR"),
        select(items.kind, items.addon_type_id).where(items.company_id == company_id,
            items.price_list_id == price_list_id, items.kind == "ADDON"),
    ).cte("required_work")
    return select(required.c.kind, required.c.target_id, catalog.c.name, catalog.c.unit, catalog.c.available
    ).select_from(required).outerjoin(catalog, and_(catalog.c.kind == required.c.kind,
                                                  catalog.c.target_id == required.c.target_id))
