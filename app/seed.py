from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security.password import hash_password
from app.modules.companies.application.service import CompaniesPlatformService
from app.modules.companies.infrastructure.models import CompanyPlanORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.identity.domain.enums import AdminScope, UserRole
from app.modules.identity.infrastructure.models import (
    AdminProfileORM,
    CompanyORM,
    UserORM,
)
from app.modules.reasons.infrastructure.default_seed import seed_default_reasons
from app.modules.reasons.infrastructure.models import ReasonORM
from app.shared.infrastructure.db.session import SessionLocal


@dataclass(frozen=True)
class SeedConfig:
    company_name: str
    admin_email: str
    admin_password: str
    admin_full_name: str


DEFAULT_DOOR_TYPES = [
    ("ENTRY", "Entry Door"),
    ("MAMAD", "Mamad Door"),
    ("FIRE", "Fire Door"),
]


def run_seed(cfg: SeedConfig, *, session_factory=SessionLocal) -> None:
    session: Session = session_factory()
    try:
        company = (
            session.query(CompanyORM)
            .filter(CompanyORM.name == cfg.company_name)
            .one_or_none()
        )
        company_created = company is None
        if company is None:
            company = CompanyORM(name=cfg.company_name, is_active=True)
            session.add(company)
            session.flush()

        admin = (
            session.query(UserORM)
            .filter(
                UserORM.company_id == company.id,
                UserORM.email == cfg.admin_email.lower(),
            )
            .one_or_none()
        )
        admin_created = admin is None
        if admin is None:
            admin = UserORM(
                company_id=company.id,
                email=cfg.admin_email.lower(),
                full_name=cfg.admin_full_name,
                role=UserRole.ADMIN,
                password_hash=hash_password(cfg.admin_password),
                is_active=True,
            )
            session.add(admin)
            session.flush()

        admin_profile = (
            session.query(AdminProfileORM)
            .filter(
                AdminProfileORM.company_id == company.id,
                AdminProfileORM.user_id == admin.id,
            )
            .one_or_none()
        )
        if admin_profile is None:
            session.add(
                AdminProfileORM(
                    company_id=company.id,
                    user_id=admin.id,
                    admin_scope=AdminScope.OWNER.value,
                    can_view_rates=True,
                    can_manage_imports=True,
                    can_manage_users=True,
                )
            )

        company_plan = (
            session.query(CompanyPlanORM)
            .filter(CompanyPlanORM.company_id == company.id)
            .one_or_none()
        )
        if company_plan is None:
            session.add(CompaniesPlatformService.build_default_plan(company.id))

        _upsert_catalog(
            session=session,
            company_id=company.id,
            model=DoorTypeORM,
            items=DEFAULT_DOOR_TYPES,
        )
        seed_default_reasons(session=session, company_id=company.id)

        session.commit()
        print("Seed completed")
        print(f"Company: {company.name} ({company.id})")
        print(f"Admin: {cfg.admin_email}")
        print(f"Created: company={company_created}, admin={admin_created}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _upsert_catalog(
    session: Session,
    company_id,
    model: type[DoorTypeORM] | type[ReasonORM],
    items: Iterable[tuple[str, str]],
) -> None:
    existing = {
        row.code: row
        for row in session.query(model).filter(model.company_id == company_id).all()
    }
    for code, name in items:
        row = existing.get(code)
        if row:
            if row.name != name:
                row.name = name
                session.add(row)
        else:
            session.add(
                model(
                    company_id=company_id,
                    code=code,
                    name=name,
                    is_active=True,
                )
            )


if __name__ == "__main__":
    cfg = SeedConfig(
        company_name=getattr(settings, "SEED_COMPANY_NAME", "DIMAX GROUP"),
        admin_email=getattr(settings, "SEED_ADMIN_EMAIL", "admin@dimax.local"),
        admin_password=getattr(settings, "SEED_ADMIN_PASSWORD", "secret123"),
        admin_full_name=getattr(settings, "SEED_ADMIN_FULL_NAME", "Admin DIMAX"),
    )
    run_seed(cfg)
