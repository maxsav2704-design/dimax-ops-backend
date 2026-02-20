from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.addons.infrastructure.models import (
    AddonTypeORM,
    ProjectAddonFactORM,
    ProjectAddonPlanORM,
)


class AddonTypeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_active(self, *, company_id: uuid.UUID) -> list[AddonTypeORM]:
        return (
            self.session.query(AddonTypeORM)
            .filter(
                AddonTypeORM.company_id == company_id,
                AddonTypeORM.deleted_at.is_(None),
                AddonTypeORM.is_active.is_(True),
            )
            .order_by(AddonTypeORM.name.asc())
            .all()
        )

    def get(
        self,
        *,
        company_id: uuid.UUID,
        addon_type_id: uuid.UUID,
    ) -> AddonTypeORM | None:
        return (
            self.session.query(AddonTypeORM)
            .filter(
                AddonTypeORM.company_id == company_id,
                AddonTypeORM.id == addon_type_id,
                AddonTypeORM.deleted_at.is_(None),
            )
            .one_or_none()
        )

    def create(self, row: AddonTypeORM) -> None:
        self.session.add(row)


class ProjectAddonPlanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        addon_type_id: uuid.UUID,
        qty_planned: Decimal,
        client_price: Decimal,
        installer_price: Decimal,
    ) -> ProjectAddonPlanORM:
        row = (
            self.session.query(ProjectAddonPlanORM)
            .filter(
                ProjectAddonPlanORM.company_id == company_id,
                ProjectAddonPlanORM.project_id == project_id,
                ProjectAddonPlanORM.addon_type_id == addon_type_id,
            )
            .one_or_none()
        )
        if not row:
            row = ProjectAddonPlanORM(
                company_id=company_id,
                project_id=project_id,
                addon_type_id=addon_type_id,
                qty_planned=qty_planned,
                client_price=client_price,
                installer_price=installer_price,
            )
        else:
            row.qty_planned = qty_planned
            row.client_price = client_price
            row.installer_price = installer_price
        self.session.add(row)
        return row

    def list_by_project(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> list[ProjectAddonPlanORM]:
        return (
            self.session.query(ProjectAddonPlanORM)
            .filter(
                ProjectAddonPlanORM.company_id == company_id,
                ProjectAddonPlanORM.project_id == project_id,
            )
            .all()
        )

    def delete(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        addon_type_id: uuid.UUID,
    ) -> None:
        (
            self.session.query(ProjectAddonPlanORM)
            .filter(
                ProjectAddonPlanORM.company_id == company_id,
                ProjectAddonPlanORM.project_id == project_id,
                ProjectAddonPlanORM.addon_type_id == addon_type_id,
            )
            .delete(synchronize_session=False)
        )


class ProjectAddonFactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, row: ProjectAddonFactORM) -> None:
        self.session.add(row)

    def exists_client_event(
        self,
        *,
        company_id: uuid.UUID,
        client_event_id: str,
    ) -> bool:
        if not client_event_id:
            return False
        return (
            self.session.query(ProjectAddonFactORM.id)
            .filter(
                ProjectAddonFactORM.company_id == company_id,
                ProjectAddonFactORM.client_event_id == client_event_id,
            )
            .first()
            is not None
        )

    def list_by_project(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> list[ProjectAddonFactORM]:
        return (
            self.session.query(ProjectAddonFactORM)
            .filter(
                ProjectAddonFactORM.company_id == company_id,
                ProjectAddonFactORM.project_id == project_id,
            )
            .order_by(ProjectAddonFactORM.done_at.desc())
            .all()
        )

    def list_by_project_all(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> list[ProjectAddonFactORM]:
        return (
            self.session.query(ProjectAddonFactORM)
            .filter(
                ProjectAddonFactORM.company_id == company_id,
                ProjectAddonFactORM.project_id == project_id,
            )
            .order_by(ProjectAddonFactORM.done_at.desc())
            .all()
        )

    def list_by_project_for_installer(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> list[ProjectAddonFactORM]:
        return (
            self.session.query(ProjectAddonFactORM)
            .filter(
                ProjectAddonFactORM.company_id == company_id,
                ProjectAddonFactORM.project_id == project_id,
                ProjectAddonFactORM.installer_id == installer_id,
            )
            .order_by(ProjectAddonFactORM.done_at.desc())
            .all()
        )
