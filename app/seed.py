from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security.password import hash_password
from app.shared.infrastructure.db.session import SessionLocal
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import CompanyORM, UserORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.reasons.infrastructure.models import ReasonORM


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

DEFAULT_REASONS = [
    ("MISSING_PARTS", "Missing parts"),
    ("DAMAGED", "Damaged door"),
    ("WRONG_SIZE", "Wrong size"),
    ("SITE_NOT_READY", "Site not ready"),
    ("CLIENT_REQUEST", "Client request"),
]

def run_seed(cfg: SeedConfig) -> None:
    session: Session = SessionLocal()
    try:
        # 1) Company: find or create
        company = (
            session.query(CompanyORM)
            .filter(CompanyORM.name == cfg.company_name)
            .one_or_none()
        )
        if not company:
            company = CompanyORM(name=cfg.company_name, is_active=True)
            session.add(company)
            session.flush()  # получаем company.id

        # 2) Admin user: find or create (by email in this company)
        admin = (
            session.query(UserORM)
            .filter(
                UserORM.company_id == company.id,
                UserORM.email == cfg.admin_email.lower(),
            )
            .one_or_none()
        )
        if not admin:
            admin = UserORM(
                company_id=company.id,
                email=cfg.admin_email.lower(),
                full_name=cfg.admin_full_name,
                role=UserRole.ADMIN,
                password_hash=hash_password(cfg.admin_password),
                is_active=True,
            )
            session.add(admin)

        # 3) Door types: upsert by code
        _upsert_catalog(
            session=session,
            company_id=company.id,
            model=DoorTypeORM,
            items=DEFAULT_DOOR_TYPES,
        )

        # 4) Reasons: upsert by code
        _upsert_catalog(
            session=session,
            company_id=company.id,
            model=ReasonORM,
            items=DEFAULT_REASONS,
        )

        session.commit()
        print("✅ Seed completed")
        print(f"Company: {company.name} ({company.id})")
        print(f"Admin: {cfg.admin_email} / {cfg.admin_password}")

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
