from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, or_

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.application.installer_api_service import (
    InstallerEarningsApiService,
)
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.workspace.api.installer_schemas import (
    InstallerWorkspaceEventDTO,
    InstallerWorkspacePriorityDoorDTO,
    InstallerWorkspaceProblemProjectDTO,
    InstallerWorkspaceResponse,
)


TZ_JERUSALEM = ZoneInfo("Asia/Jerusalem")


class InstallerWorkspaceApiService:
    @staticmethod
    def get_workspace(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> InstallerWorkspaceResponse:
        now_local = datetime.now(TZ_JERUSALEM)
        today_start_local = datetime.combine(
            now_local.date(),
            time.min,
            tzinfo=TZ_JERUSALEM,
        )
        today_end_local = today_start_local + timedelta(days=1)
        today_start_utc = today_start_local.astimezone(timezone.utc)
        today_end_utc = today_end_local.astimezone(timezone.utc)

        today_events = uow.calendar.list_range(
            company_id=company_id,
            starts_at=today_start_utc,
            ends_at=today_end_utc,
            installer_id=installer_id,
        )
        priority_doors = (
            uow.session.query(DoorORM)
            .filter(
                DoorORM.company_id == company_id,
                DoorORM.installer_id == installer_id,
                DoorORM.is_critical.is_(True),
                DoorORM.status.notin_(
                    [
                        DoorStatus.INSTALLED,
                        DoorStatus.CANCELLED,
                        DoorStatus.LOCKED,
                    ]
                ),
            )
            .order_by(DoorORM.updated_at.desc())
            .all()
        )
        problem_project_ids = (
            uow.session.query(distinct(ProjectORM.id))
            .join(DoorORM, DoorORM.project_id == ProjectORM.id)
            .filter(
                ProjectORM.company_id == company_id,
                DoorORM.installer_id == installer_id,
                or_(
                    ProjectORM.health_status == "BLOCKED",
                    ProjectORM.health_status == "AT_RISK",
                ),
            )
            .all()
        )
        problem_projects = uow.projects.list_by_ids(
            company_id=company_id,
            ids=[row[0] for row in problem_project_ids],
        )
        earnings_today = InstallerEarningsApiService.summary(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            period="day",
            anchor_date=now_local.date(),
        ).total

        return InstallerWorkspaceResponse(
            today_tasks=[
                InstallerWorkspaceEventDTO(
                    id=row.id,
                    title=row.title,
                    starts_at=row.starts_at,
                    ends_at=row.ends_at,
                    project_id=row.project_id,
                )
                for row in today_events
            ],
            priority_tasks=[
                InstallerWorkspacePriorityDoorDTO(
                    id=row.id,
                    project_id=row.project_id,
                    unit_label=row.unit_label,
                    status=row.status.value if hasattr(row.status, "value") else str(row.status),
                    is_critical=bool(getattr(row, "is_critical", False)),
                )
                for row in priority_doors
            ],
            problem_projects=[
                InstallerWorkspaceProblemProjectDTO(
                    id=row.id,
                    project_id=row.id,
                    name=row.name,
                    address=row.address,
                    health_status=str(getattr(row, "health_status", "NORMAL")),
                )
                for row in problem_projects
            ],
            earnings_today=str(Decimal(str(earnings_today or 0))),
        )
