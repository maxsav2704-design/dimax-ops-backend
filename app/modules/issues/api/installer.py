from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.pagination import paginate_items, pagination_params
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.issues.api.installer_schemas import (
    InstallerIssueCreateBody,
    InstallerIssueReportDTO,
    InstallerIssueUpdateBody,
    InstallerIssuesListResponse,
)
from app.modules.issues.api.schemas import IssueMediaResponse
from app.modules.issues.application.installer_api_service import (
    InstallerIssuesApiService,
)


router = APIRouter(prefix="/installer/issues", tags=["Installer / Issues"])


@router.get("", response_model=InstallerIssuesListResponse)
def list_my_issues(
    pagination: tuple[int, int] = Depends(pagination_params),
    user: CurrentUser = Depends(require_installer),
    _installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    page, per_page = pagination
    with uow:
        return InstallerIssuesListResponse(
            **paginate_items(
                InstallerIssuesApiService.list_issues(
                    uow,
                    company_id=user.company_id,
                    created_by_user_id=user.id,
                ),
                page=page,
                per_page=per_page,
            )
        )


@router.post("", response_model=InstallerIssueReportDTO, status_code=201)
def create_issue(
    body: InstallerIssueCreateBody,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return InstallerIssuesApiService.create_issue(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            created_by_user_id=user.id,
            door_id=body.door_id,
            title=body.title,
            details=body.details,
        )


@router.patch("/{issue_id}", response_model=InstallerIssueReportDTO)
def update_issue(
    issue_id: UUID,
    body: InstallerIssueUpdateBody,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return InstallerIssuesApiService.update_issue_comment(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            user_id=user.id,
            issue_id=issue_id,
            comment=body.comment,
        )


@router.get("/{issue_id}/media", response_model=IssueMediaResponse)
def list_issue_media(
    issue_id: UUID,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        InstallerIssuesApiService.ensure_issue_visible(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            user_id=user.id,
            issue_id=issue_id,
        )
        return IssueMediaResponse(items=[])
