from __future__ import annotations

import base64
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.projects.api.schemas import (
    AssignInstallerBody,
    FailedImportRunsQueueResponse,
    ImportDoorsFromFileBody,
    ImportMappingProfilesResponse,
    ImportDoorsFromFileResponse,
    ImportDoorsResponse,
    ImportDoorsBody,
    OkResponse,
    ProjectCreateResponse,
    ProjectCreateBody,
    ProjectDetailsResponse,
    ProjectDoorsLayoutResponse,
    ProjectBulkImportReconcileBody,
    ProjectBulkImportReconcileResponse,
    ProjectLatestImportReviewResponse,
    ProjectImportRunDetailsDTO,
    ProjectImportRunsResponse,
    ProjectListResponse,
    RetryFailedImportRunsBody,
    RetryFailedImportRunsResponse,
    ProjectUpdateBody,
)
from app.modules.projects.application.admin_service import ProjectAdminService


router = APIRouter(prefix="/admin/projects", tags=["Admin / Projects"])


@router.get("", response_model=ProjectListResponse)
def list_projects(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.list_projects(
            uow,
            company_id=user.company_id,
            q=q,
            status=status,
            limit=limit,
            offset=offset,
        )


@router.post("", response_model=ProjectCreateResponse)
def create_project(
    body: ProjectCreateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.create_project(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            name=body.name,
            address=body.address,
            developer_company=body.developer_company,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            contact_email=body.contact_email,
        )


@router.patch("/{project_id}", response_model=OkResponse)
def update_project(
    project_id: UUID,
    body: ProjectUpdateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ProjectAdminService.update_project(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            payload=body.model_dump(exclude_unset=True),
        )
    return OkResponse()


@router.delete("/{project_id}", response_model=OkResponse)
def delete_project(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ProjectAdminService.delete_project(
            uow,
            company_id=user.company_id,
            project_id=project_id,
        )
    return OkResponse()


@router.post("/{project_id}/doors/import", response_model=ImportDoorsResponse)
def import_doors(
    project_id: UUID,
    body: ImportDoorsBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.import_doors(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            project_id=project_id,
            rows=[r.model_dump() for r in body.rows],
        )


@router.post(
    "/{project_id}/doors/import-file",
    response_model=ImportDoorsFromFileResponse,
)
def import_doors_from_file(
    project_id: UUID,
    body: ImportDoorsFromFileBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.import_doors_from_file(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            project_id=project_id,
            filename=body.filename,
            content_base64=body.content_base64,
            default_door_type_id=body.default_door_type_id,
            default_our_price=body.default_our_price,
            delimiter=body.delimiter,
            mapping_profile=body.mapping_profile,
            strict_required_fields=body.strict_required_fields,
            create_missing_door_types=body.create_missing_door_types,
            analyze_only=body.analyze_only,
        )


@router.get(
    "/import-mapping-profiles",
    response_model=ImportMappingProfilesResponse,
)
def list_import_mapping_profiles(
    user: CurrentUser = Depends(require_admin),
):
    return ProjectAdminService.list_import_mapping_profiles(company_id=user.company_id)


@router.get(
    "/{project_id}/doors/import-history",
    response_model=ProjectImportRunsResponse,
)
def project_import_history(
    project_id: UUID,
    mode: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.import_runs_history(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            mode=mode,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/{project_id}/doors/import-runs/{run_id}",
    response_model=ProjectImportRunDetailsDTO,
)
def project_import_run_details(
    project_id: UUID,
    run_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.import_run_details(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            run_id=run_id,
        )


@router.post(
    "/{project_id}/doors/import-runs/{run_id}/retry",
    response_model=ImportDoorsFromFileResponse,
)
def retry_project_import_run(
    project_id: UUID,
    run_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.retry_import_run(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            project_id=project_id,
            run_id=run_id,
        )


@router.post(
    "/import-runs/review-latest",
    response_model=ProjectLatestImportReviewResponse,
)
def review_latest_imports(
    body: ProjectBulkImportReconcileBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.review_latest_imports(
            uow,
            company_id=user.company_id,
            project_ids=body.project_ids,
            only_failed_runs=body.only_failed_runs,
        )


@router.post(
    "/import-runs/reconcile-latest",
    response_model=ProjectBulkImportReconcileResponse,
)
def bulk_reconcile_latest_imports(
    body: ProjectBulkImportReconcileBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.bulk_reconcile_latest_imports(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            project_ids=body.project_ids,
            only_failed_runs=body.only_failed_runs,
        )


@router.get(
    "/import-runs/failed-queue",
    response_model=FailedImportRunsQueueResponse,
)
def failed_import_runs_queue(
    project_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.failed_import_runs_queue(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )


@router.post(
    "/import-runs/retry-failed",
    response_model=RetryFailedImportRunsResponse,
)
def retry_failed_import_runs(
    body: RetryFailedImportRunsBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.retry_failed_runs_bulk(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            run_ids=body.run_ids,
        )


@router.post(
    "/{project_id}/doors/import-upload",
    response_model=ImportDoorsFromFileResponse,
)
async def import_doors_from_upload(
    project_id: UUID,
    file: UploadFile = File(...),
    default_door_type_id: UUID | None = Form(default=None),
    default_our_price: Decimal = Form(default=Decimal("0")),
    delimiter: str | None = Form(default=None),
    mapping_profile: str = Form(default="auto_v1"),
    strict_required_fields: bool | None = Form(default=None),
    create_missing_door_types: bool = Form(default=False),
    analyze_only: bool = Form(default=False),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    filename = (file.filename or "").strip()
    if len(filename) < 3:
        raise HTTPException(status_code=422, detail="filename is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="file is empty")

    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="file is too large (max 20MB)")

    with uow:
        return ProjectAdminService.import_doors_from_file(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            project_id=project_id,
            filename=filename,
            content_base64=base64.b64encode(content).decode("ascii"),
            default_door_type_id=default_door_type_id,
            default_our_price=default_our_price,
            delimiter=delimiter,
            mapping_profile=mapping_profile,
            strict_required_fields=strict_required_fields,
            create_missing_door_types=create_missing_door_types,
            analyze_only=analyze_only,
        )


@router.get("/{project_id}", response_model=ProjectDetailsResponse)
def project_details(
    project_id: UUID,
    order_number: str | None = Query(default=None, max_length=80),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.project_details(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            order_number=order_number,
        )


@router.get("/{project_id}/doors/layout", response_model=ProjectDoorsLayoutResponse)
def project_doors_layout(
    project_id: UUID,
    order_number: str | None = Query(default=None, max_length=80),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.project_doors_layout(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            order_number=order_number,
        )


@router.post("/doors/{door_id}/assign-installer", response_model=OkResponse)
def assign_installer_to_door(
    door_id: UUID,
    body: AssignInstallerBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ProjectAdminService.assign_installer_to_door(
            uow,
            company_id=user.company_id,
            door_id=door_id,
            installer_id=body.installer_id,
        )
    return OkResponse()
