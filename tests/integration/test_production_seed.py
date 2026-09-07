from __future__ import annotations

import uuid

from sqlalchemy.orm import sessionmaker

from app.core.security.password import verify_password
from app.modules.companies.infrastructure.models import CompanyPlanORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.identity.domain.enums import AdminScope, UserRole
from app.modules.identity.infrastructure.models import (
    AdminProfileORM,
    CompanyORM,
    UserORM,
)
from app.modules.reasons.infrastructure.models import ReasonORM
from app.seed import SeedConfig, run_seed


def test_production_seed_is_idempotent_and_creates_owner_access(
    db_session,
    capsys,
) -> None:
    suffix = uuid.uuid4().hex
    company_name = f"Production Seed {suffix}"
    admin_email = f"owner-{suffix}@dimax.co.il"
    admin_password = "ProductionSeedPass!2026"
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    config = SeedConfig(
        company_name=company_name,
        admin_email=admin_email,
        admin_password=admin_password,
        admin_full_name="DIMAX Owner",
    )

    try:
        run_seed(config, session_factory=session_factory)
        run_seed(config, session_factory=session_factory)

        company = (
            db_session.query(CompanyORM)
            .filter(CompanyORM.name == company_name)
            .one()
        )
        admin = (
            db_session.query(UserORM)
            .filter(
                UserORM.company_id == company.id,
                UserORM.email == admin_email,
            )
            .one()
        )
        profile = (
            db_session.query(AdminProfileORM)
            .filter(
                AdminProfileORM.company_id == company.id,
                AdminProfileORM.user_id == admin.id,
            )
            .one()
        )

        assert admin.role == UserRole.ADMIN
        assert verify_password(admin_password, admin.password_hash) is True
        assert profile.admin_scope == AdminScope.OWNER.value
        assert profile.can_view_rates is True
        assert profile.can_manage_imports is True
        assert profile.can_manage_users is True
        assert (
            db_session.query(CompanyPlanORM)
            .filter(CompanyPlanORM.company_id == company.id)
            .count()
            == 1
        )
        assert (
            db_session.query(DoorTypeORM)
            .filter(DoorTypeORM.company_id == company.id)
            .count()
            >= 3
        )
        assert (
            db_session.query(ReasonORM)
            .filter(ReasonORM.company_id == company.id)
            .count()
            > 0
        )
        assert admin_password not in capsys.readouterr().out
    finally:
        company = (
            db_session.query(CompanyORM)
            .filter(CompanyORM.name == company_name)
            .one_or_none()
        )
        if company is not None:
            for model in (
                AdminProfileORM,
                CompanyPlanORM,
                DoorTypeORM,
                ReasonORM,
                UserORM,
            ):
                db_session.query(model).filter(
                    model.company_id == company.id
                ).delete(synchronize_session=False)
            db_session.delete(company)
            db_session.commit()
