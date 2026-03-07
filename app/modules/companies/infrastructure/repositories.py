from __future__ import annotations

import uuid
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.companies.infrastructure.models import CompanyPlanORM
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import CompanyORM, UserORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.infrastructure.models import ProjectORM


class CompanyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, company: CompanyORM) -> None:
        self.session.add(company)

    def get(self, company_id: uuid.UUID) -> CompanyORM | None:
        stmt = select(CompanyORM).where(CompanyORM.id == company_id)
        return self.session.execute(stmt).scalars().first()

    def get_by_name(self, name: str) -> CompanyORM | None:
        stmt = select(CompanyORM).where(func.lower(CompanyORM.name) == name.strip().lower())
        return self.session.execute(stmt).scalars().first()

    def list(
        self,
        *,
        include_inactive: bool,
        limit: int,
        offset: int,
    ) -> list[CompanyORM]:
        stmt = select(CompanyORM)
        if not include_inactive:
            stmt = stmt.where(CompanyORM.is_active.is_(True))
        stmt = stmt.order_by(CompanyORM.created_at.desc()).limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars().all())

    def count(self, *, include_inactive: bool) -> int:
        stmt = select(func.count(CompanyORM.id))
        if not include_inactive:
            stmt = stmt.where(CompanyORM.is_active.is_(True))
        return int(self.session.execute(stmt).scalar_one())

    def list_all(self) -> list[CompanyORM]:
        stmt = select(CompanyORM).where(CompanyORM.is_active.is_(True))
        return list(self.session.execute(stmt).scalars().all())

    def list_ids(self) -> list[uuid.UUID]:
        """Return list of active company IDs (for workers, no ORM load)."""
        rows = (
            self.session.query(CompanyORM.id)
            .filter(CompanyORM.is_active.is_(True))
            .all()
        )
        return [r[0] for r in rows]


class CompanyPlanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_company_id(self, company_id: uuid.UUID) -> CompanyPlanORM | None:
        stmt = select(CompanyPlanORM).where(CompanyPlanORM.company_id == company_id)
        return self.session.execute(stmt).scalars().first()

    def save(self, obj: CompanyPlanORM) -> None:
        self.session.add(obj)

    def usage_summary(self, company_id: uuid.UUID) -> dict[str, int]:
        active_users = self._count(
            select(func.count(UserORM.id)).where(
                UserORM.company_id == company_id,
                UserORM.is_active.is_(True),
            )
        )
        active_admin_users = self._count(
            select(func.count(UserORM.id)).where(
                UserORM.company_id == company_id,
                UserORM.is_active.is_(True),
                UserORM.role == UserRole.ADMIN,
            )
        )
        active_installer_users = self._count(
            select(func.count(UserORM.id)).where(
                UserORM.company_id == company_id,
                UserORM.is_active.is_(True),
                UserORM.role == UserRole.INSTALLER,
            )
        )
        active_installers = self._count(
            select(func.count(InstallerORM.id)).where(
                InstallerORM.company_id == company_id,
                InstallerORM.deleted_at.is_(None),
                InstallerORM.is_active.is_(True),
            )
        )
        active_projects = self._count(
            select(func.count(ProjectORM.id)).where(
                ProjectORM.company_id == company_id,
                ProjectORM.deleted_at.is_(None),
            )
        )
        total_doors = self._count(
            select(func.count(DoorORM.id)).where(DoorORM.company_id == company_id)
        )
        return {
            "active_users": active_users,
            "active_admin_users": active_admin_users,
            "active_installer_users": active_installer_users,
            "active_installers": active_installers,
            "active_projects": active_projects,
            "total_doors": total_doors,
        }

    def max_doors_in_project(self, company_id: uuid.UUID) -> int:
        rows = (
            self.session.query(func.count(DoorORM.id))
            .filter(DoorORM.company_id == company_id)
            .group_by(DoorORM.project_id)
            .all()
        )
        if not rows:
            return 0
        return int(max(row[0] for row in rows))

    def limits_kpi(self, company_id: uuid.UUID) -> dict:
        plan = self.get_by_company_id(company_id)
        usage = self.usage_summary(company_id)
        doors_per_project_current = self.max_doors_in_project(company_id)

        if plan is None:
            return {
                "plan_code": None,
                "plan_active": None,
                "total_doors": usage["total_doors"],
                "users": self._metric(current=usage["active_users"], limit=None),
                "admin_users": self._metric(
                    current=usage["active_admin_users"],
                    limit=None,
                ),
                "installer_users": self._metric(
                    current=usage["active_installer_users"],
                    limit=None,
                ),
                "installers": self._metric(current=usage["active_installers"], limit=None),
                "projects": self._metric(current=usage["active_projects"], limit=None),
                "doors_per_project": self._metric(
                    current=doors_per_project_current,
                    limit=None,
                ),
            }

        return {
            "plan_code": plan.plan_code,
            "plan_active": plan.is_active,
            "total_doors": usage["total_doors"],
            "users": self._metric(current=usage["active_users"], limit=plan.max_users),
            "admin_users": self._metric(
                current=usage["active_admin_users"],
                limit=plan.max_admin_users,
            ),
            "installer_users": self._metric(
                current=usage["active_installer_users"],
                limit=plan.max_installer_users,
            ),
            "installers": self._metric(
                current=usage["active_installers"],
                limit=plan.max_installers,
            ),
            "projects": self._metric(current=usage["active_projects"], limit=plan.max_projects),
            "doors_per_project": self._metric(
                current=doors_per_project_current,
                limit=plan.max_doors_per_project,
            ),
        }

    def _count(self, stmt) -> int:
        return int(self.session.execute(stmt).scalar_one())

    def _metric(self, *, current: int, limit: int | None) -> dict:
        is_enforced = limit is not None
        utilization_pct = None
        is_exceeded = False
        if limit is not None:
            utilization_pct = round((current / limit) * 100, 2)
            is_exceeded = current > limit
        return {
            "current": current,
            "max": limit,
            "utilization_pct": utilization_pct,
            "is_enforced": is_enforced,
            "is_exceeded": is_exceeded,
        }
