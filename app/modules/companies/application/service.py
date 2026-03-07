from __future__ import annotations

import uuid
from decimal import Decimal

from app.core.security.password import hash_password
from app.modules.companies.api.schemas import (
    PlatformCompanyCreateDTO,
    PlatformCompanyPlanUpdateDTO,
    PlatformCompanyUserCreateDTO,
)
from app.modules.companies.application.alerts_service import (
    CompanyLimitAlertsService,
    SYSTEM_ACTOR_ID,
)
from app.modules.companies.application.limits_service import CompanyLimitsService
from app.modules.companies.domain.errors import CompanyAlreadyExists, CompanyNotFound
from app.modules.companies.infrastructure.models import CompanyPlanORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import CompanyORM, UserORM
from app.modules.reasons.infrastructure.models import ReasonORM
from app.shared.domain.errors import ValidationError

DEFAULT_DOOR_TYPES: tuple[tuple[str, str], ...] = (
    ("DIRA", "Apartment Door"),
    ("MAMAD", "Safe Room Door"),
    ("MADREGOT", "Stairwell Door"),
    ("MAHSAN", "Storage Door"),
    ("HEDER_ASHPA", "Trash Room Door"),
    ("LOBI_MAALIT", "Elevator Lobby Door"),
)

DEFAULT_REASONS: tuple[tuple[str, str], ...] = (
    ("MISSING_PARTS", "Missing parts"),
    ("DAMAGED", "Damaged door"),
    ("WRONG_SIZE", "Wrong size"),
    ("SITE_NOT_READY", "Site not ready"),
    ("CLIENT_REQUEST", "Client request"),
)


class CompaniesPlatformService:
    @staticmethod
    def list_companies(
        uow,
        *,
        include_inactive: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[CompanyORM], int]:
        items = uow.companies.list(
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
        total = uow.companies.count(include_inactive=include_inactive)
        return items, total

    @staticmethod
    def create_company_with_admin(
        uow,
        *,
        data: PlatformCompanyCreateDTO,
    ) -> tuple[CompanyORM, UserORM, CompanyPlanORM]:
        company_name = data.name.strip()
        if not company_name:
            raise ValidationError("Company name cannot be empty")
        if uow.companies.get_by_name(company_name):
            raise CompanyAlreadyExists("Company with this name already exists")

        company = CompanyORM(name=company_name, is_active=True)
        uow.companies.add(company)
        uow.session.flush()

        admin = UserORM(
            company_id=company.id,
            email=str(data.admin_email).lower(),
            full_name=data.admin_full_name.strip(),
            role=UserRole.ADMIN,
            password_hash=hash_password(data.admin_password),
            is_active=True,
        )
        uow.users.add(admin)
        uow.session.flush()

        CompaniesPlatformService._seed_default_catalogs(uow, company_id=company.id)

        plan = CompaniesPlatformService._build_default_plan(company.id)
        uow.company_plans.save(plan)
        uow.session.flush()

        return company, admin, plan

    @staticmethod
    def update_company_status(
        uow,
        *,
        company_id: uuid.UUID,
        is_active: bool,
    ) -> CompanyORM:
        company = uow.companies.get(company_id)
        if company is None:
            raise CompanyNotFound("Company not found")

        company.is_active = is_active
        uow.companies.add(company)
        return company

    @staticmethod
    def get_company_plan(
        uow,
        *,
        company_id: uuid.UUID,
    ) -> CompanyPlanORM:
        company = uow.companies.get(company_id)
        if company is None:
            raise CompanyNotFound("Company not found")

        plan = uow.company_plans.get_by_company_id(company_id)
        if plan is None:
            plan = CompaniesPlatformService._build_default_plan(company_id)
            uow.company_plans.save(plan)
            uow.session.flush()
        return plan

    @staticmethod
    def update_company_plan(
        uow,
        *,
        company_id: uuid.UUID,
        data: PlatformCompanyPlanUpdateDTO,
    ) -> CompanyPlanORM:
        if data.max_users is not None and data.max_admin_users is not None:
            if data.max_admin_users > data.max_users:
                raise ValidationError("max_admin_users cannot exceed max_users")
        if data.max_users is not None and data.max_installer_users is not None:
            if data.max_installer_users > data.max_users:
                raise ValidationError("max_installer_users cannot exceed max_users")

        plan = CompaniesPlatformService.get_company_plan(uow, company_id=company_id)
        plan.plan_code = data.plan_code.strip().lower()
        plan.is_active = data.is_active
        plan.max_users = data.max_users
        plan.max_admin_users = data.max_admin_users
        plan.max_installer_users = data.max_installer_users
        plan.max_installers = data.max_installers
        plan.max_projects = data.max_projects
        plan.max_doors_per_project = data.max_doors_per_project
        plan.monthly_price = data.monthly_price
        plan.currency = data.currency.strip().upper()
        plan.notes = data.notes.strip() if data.notes else None
        uow.company_plans.save(plan)
        return plan

    @staticmethod
    def create_company_user(
        uow,
        *,
        company_id: uuid.UUID,
        data: PlatformCompanyUserCreateDTO,
    ) -> UserORM:
        company = uow.companies.get(company_id)
        if company is None:
            raise CompanyNotFound("Company not found")

        CompanyLimitsService.assert_can_create_user(
            uow,
            company_id=company_id,
            role=data.role,
        )

        full_name = data.full_name.strip()
        if not full_name:
            raise ValidationError("full_name cannot be empty")

        user = UserORM(
            company_id=company_id,
            email=str(data.email).lower(),
            full_name=full_name,
            role=data.role,
            password_hash=hash_password(data.password),
            is_active=data.is_active,
        )
        uow.users.add(user)
        uow.session.flush()
        CompanyLimitAlertsService.evaluate_and_alert(
            uow,
            company_id=company_id,
            actor_user_id=SYSTEM_ACTOR_ID,
            metric_keys=["users"],
        )
        return user

    @staticmethod
    def get_company_usage(
        uow,
        *,
        company_id: uuid.UUID,
    ) -> dict[str, int]:
        company = uow.companies.get(company_id)
        if company is None:
            raise CompanyNotFound("Company not found")
        return uow.company_plans.usage_summary(company_id)

    @staticmethod
    def _seed_default_catalogs(uow, *, company_id: uuid.UUID) -> None:
        for code, name in DEFAULT_DOOR_TYPES:
            uow.door_types.save(
                DoorTypeORM(
                    company_id=company_id,
                    code=code,
                    name=name,
                    is_active=True,
                )
            )
        for code, name in DEFAULT_REASONS:
            uow.reasons.save(
                ReasonORM(
                    company_id=company_id,
                    code=code,
                    name=name,
                    is_active=True,
                )
            )

    @staticmethod
    def _build_default_plan(company_id: uuid.UUID) -> CompanyPlanORM:
        return CompanyPlanORM(
            company_id=company_id,
            plan_code="trial",
            is_active=True,
            max_users=25,
            max_admin_users=10,
            max_installer_users=15,
            max_installers=40,
            max_projects=120,
            max_doors_per_project=6000,
            monthly_price=Decimal("0.00"),
            currency="USD",
            notes="Auto provisioned default trial plan",
        )
