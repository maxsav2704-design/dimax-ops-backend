from __future__ import annotations

import uuid

from app.modules.companies.domain.errors import CompanyPlanLimitExceeded
from app.modules.identity.domain.enums import UserRole


class CompanyLimitsService:
    @staticmethod
    def assert_can_create_user(
        uow,
        *,
        company_id: uuid.UUID,
        role: UserRole,
    ) -> None:
        plans_repo = getattr(uow, "company_plans", None)
        if plans_repo is None:
            return
        plan = CompanyLimitsService._get_enforced_plan_or_none(uow, company_id=company_id)
        usage = plans_repo.usage_summary(company_id)

        if plan is not None and plan.max_users is not None:
            current = usage["active_users"]
            if current >= plan.max_users:
                raise CompanyPlanLimitExceeded(
                    "User limit reached for current plan",
                    details={
                        "limit_name": "max_users",
                        "current": current,
                        "max": plan.max_users,
                        "role": role.value,
                    },
                )

        if plan is None:
            return

        if role == UserRole.ADMIN:
            role_limit = plan.max_admin_users
            role_current = usage["active_admin_users"]
            limit_name = "max_admin_users"
            message = "Admin user limit reached for current plan"
        else:
            role_limit = plan.max_installer_users
            role_current = usage["active_installer_users"]
            limit_name = "max_installer_users"
            message = "Installer user limit reached for current plan"

        if role_limit is None:
            return

        if role_current >= role_limit:
            raise CompanyPlanLimitExceeded(
                message,
                details={
                    "limit_name": limit_name,
                    "current": role_current,
                    "max": role_limit,
                    "role": role.value,
                },
            )

    @staticmethod
    def assert_can_create_project(uow, *, company_id: uuid.UUID) -> None:
        plan = CompanyLimitsService._get_enforced_plan_or_none(uow, company_id=company_id)
        if plan is None or plan.max_projects is None:
            return
        usage = uow.company_plans.usage_summary(company_id)
        current = usage["active_projects"]
        if current >= plan.max_projects:
            raise CompanyPlanLimitExceeded(
                "Project limit reached for current plan",
                details={
                    "limit_name": "max_projects",
                    "current": current,
                    "max": plan.max_projects,
                },
            )

    @staticmethod
    def assert_can_create_installer(uow, *, company_id: uuid.UUID) -> None:
        plan = CompanyLimitsService._get_enforced_plan_or_none(uow, company_id=company_id)
        if plan is None or plan.max_installers is None:
            return
        usage = uow.company_plans.usage_summary(company_id)
        current = usage["active_installers"]
        if current >= plan.max_installers:
            raise CompanyPlanLimitExceeded(
                "Installer limit reached for current plan",
                details={
                    "limit_name": "max_installers",
                    "current": current,
                    "max": plan.max_installers,
                },
            )

    @staticmethod
    def assert_can_add_doors_to_project(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        adding_count: int,
    ) -> None:
        if adding_count <= 0:
            return
        plan = CompanyLimitsService._get_enforced_plan_or_none(uow, company_id=company_id)
        if plan is None or plan.max_doors_per_project is None:
            return

        current = uow.doors.count_by_project(company_id=company_id, project_id=project_id)
        projected = current + adding_count
        if projected > plan.max_doors_per_project:
            raise CompanyPlanLimitExceeded(
                "Door limit per project reached for current plan",
                details={
                    "limit_name": "max_doors_per_project",
                    "current": current,
                    "adding": adding_count,
                    "projected": projected,
                    "max": plan.max_doors_per_project,
                    "project_id": str(project_id),
                },
            )

    @staticmethod
    def _get_enforced_plan_or_none(uow, *, company_id: uuid.UUID):
        plans_repo = getattr(uow, "company_plans", None)
        if plans_repo is None:
            return None
        plan = plans_repo.get_by_company_id(company_id)
        if plan is None:
            # Legacy tenants without plan are not blocked.
            return None
        if not plan.is_active:
            raise CompanyPlanLimitExceeded(
                "Company plan is inactive",
                details={"company_id": str(company_id)},
            )
        return plan
