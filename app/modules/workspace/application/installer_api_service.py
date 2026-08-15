from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, or_

from app.modules.calendar.application.api_service import CalendarApiService
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.application.installer_api_service import (
    InstallerEarningsApiService,
)
from app.modules.issues.application.installer_api_service import InstallerIssuesApiService
from app.modules.projects.application.installer_service import ProjectInstallerService
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.sync.api.installer_schemas import (
    InstallerSyncQueueItemDTO,
    InstallerSyncQueueListResponse,
)
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
        actor_user_id: uuid.UUID,
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
        now_utc = now_local.astimezone(timezone.utc)
        calendar_end_utc = now_utc + timedelta(days=7)
        task_start_utc = today_start_utc - timedelta(days=7)

        today_events = uow.calendar.list_range(
            company_id=company_id,
            starts_at=today_start_utc,
            ends_at=today_end_utc,
            installer_id=installer_id,
        )
        projects = ProjectInstallerService.list_my_projects(
            uow,
            company_id=company_id,
            installer_id=installer_id,
        )["items"]
        events = CalendarApiService.list_events(
            uow,
            company_id=company_id,
            starts_at=now_utc,
            ends_at=calendar_end_utc,
            installer_id=installer_id,
        ).items
        task_events = CalendarApiService.list_events(
            uow,
            company_id=company_id,
            starts_at=task_start_utc,
            ends_at=today_end_utc,
            installer_id=installer_id,
        ).items
        issues = InstallerIssuesApiService.list_issues(
            uow,
            company_id=company_id,
            created_by_user_id=actor_user_id,
        )
        earnings_summary = InstallerEarningsApiService.summary(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            period="month",
            anchor_date=None,
        )
        sync_queue_rows = uow.sync_queue.list_for_user(
            company_id=company_id,
            user_id=actor_user_id,
        )
        sync_queue_items = [
            InstallerSyncQueueItemDTO(
                id=row.id,
                project_id=row.project_id,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                operation_type=row.operation_type,
                payload=row.payload or {},
                base_version=row.base_version,
                status=row.status,
                conflict_code=row.conflict_code,
                created_at=row.created_at,
                synced_at=row.synced_at,
            )
            for row in sync_queue_rows[:100]
        ]
        sync_queue = InstallerSyncQueueListResponse(
            items=sync_queue_items,
            pagination={
                "page": 1,
                "per_page": 100,
                "total": len(sync_queue_rows),
                "total_pages": max((len(sync_queue_rows) + 99) // 100, 1),
            },
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
        earnings_today = InstallerEarningsApiService.total_for_range(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            period_start=today_start_utc,
            period_end=today_end_utc,
        )

        return InstallerWorkspaceResponse(
            projects=projects,
            events=events,
            task_events=task_events,
            issues=issues,
            earnings_summary=earnings_summary,
            sync_queue=sync_queue,
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
