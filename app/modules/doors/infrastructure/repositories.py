from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import distinct
from sqlalchemy.orm import Session

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM


class DoorRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, *, company_id: uuid.UUID, door_id: uuid.UUID
    ) -> DoorORM | None:
        return (
            self.session.query(DoorORM)
            .filter(DoorORM.company_id == company_id, DoorORM.id == door_id)
            .one_or_none()
        )

    def save(self, door: DoorORM) -> None:
        self.session.add(door)

    def add_many(self, doors: list[DoorORM]) -> None:
        self.session.add_all(doors)

    def list_by_project(
        self, *, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> list[DoorORM]:
        return (
            self.session.query(DoorORM)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.project_id == project_id,
            )
            .order_by(DoorORM.unit_label.asc())
            .all()
        )

    def count_not_installed(
        self, *, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> int:
        return (
            self.session.query(DoorORM)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.project_id == project_id,
                DoorORM.status == DoorStatus.NOT_INSTALLED,
            )
            .count()
        )

    def list_by_project_for_installer(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> list[DoorORM]:
        return (
            self.session.query(DoorORM)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.project_id == project_id,
                DoorORM.installer_id == installer_id,
            )
            .order_by(DoorORM.unit_label.asc())
            .all()
        )

    def list_project_ids_for_installer(
        self,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        rows = (
            self.session.query(distinct(DoorORM.project_id))
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.installer_id == installer_id,
            )
            .all()
        )
        return [r[0] for r in rows]

    def find_project_ids_by_installers(
        self,
        *,
        company_id: uuid.UUID,
        installer_ids: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        if not installer_ids:
            return []
        rows = (
            self.session.query(distinct(DoorORM.project_id))
            .filter(DoorORM.company_id == company_id)
            .filter(DoorORM.installer_id.in_(installer_ids))
            .all()
        )
        return [r[0] for r in rows]

    def list_all_for_installer(
        self,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> list[dict]:
        rows = (
            self.session.query(DoorORM)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.installer_id == installer_id,
            )
            .order_by(DoorORM.project_id.asc())
            .all()
        )
        return [
            {
                "id": str(r.id),
                "project_id": str(r.project_id),
                "door_type_id": str(r.door_type_id),
                "unit_label": r.unit_label,
                "status": str(r.status),
                "comment": r.comment,
                "updated_at": (
                    r.updated_at.isoformat() if r.updated_at else None
                ),
            }
            for r in rows
        ]

    def list_changes_for_installer(
        self,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        since: datetime | None,
    ) -> list[dict]:
        q = self.session.query(DoorORM).filter(
            DoorORM.company_id == company_id,
            DoorORM.installer_id == installer_id,
        )
        if since is not None:
            q = q.filter(DoorORM.updated_at > since)

        rows = q.order_by(DoorORM.updated_at.asc()).limit(2000).all()
        return [
            {
                "id": r.id,
                "project_id": r.project_id,
                "door_type_id": r.door_type_id,
                "unit_label": r.unit_label,
                "status": str(r.status),
                "comment": r.comment,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]
