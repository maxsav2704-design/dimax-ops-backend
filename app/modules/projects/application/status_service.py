from __future__ import annotations

import uuid

from app.modules.projects.domain.enums import ProjectStatus


class ProjectStatusService:
    @staticmethod
    def recalc_and_set(
        *, uow, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> None:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            return  # проект мог быть удалён — не падаем

        not_installed = uow.doors.count_not_installed(
            company_id=company_id, project_id=project_id
        )
        project.status = (
            ProjectStatus.PROBLEM if not_installed > 0 else ProjectStatus.OK
        )
        uow.projects.save(project)
