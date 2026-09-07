from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.v1.deps import (
    CurrentUser,
    ensure_admin_can_manage_imports,
    get_uow,
    require_admin,
)
from app.core.config import settings
from app.integrations.storage.storage_service import StorageService
from app.modules.documents.api.schemas import (
    DocumentGenerationDTO,
    DocumentGenerationsResponse,
    DocumentTemplateDTO,
    DocumentTemplatesResponse,
    DocumentTemplateUpdateBody,
    ProjectDocumentContextResponse,
    RenderProjectDocumentBody,
)
from app.modules.documents.application.service import DocumentsAdminService
from app.modules.files.infrastructure.models import FileDownloadEventORM
from app.shared.domain.errors import NotFound


router = APIRouter(prefix="/admin/documents", tags=["Admin / Documents"])


@router.get("/templates", response_model=DocumentTemplatesResponse)
def list_templates(
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return DocumentsAdminService.list_templates(uow, company_id=user.company_id)


@router.post("/templates", response_model=DocumentTemplateDTO, status_code=201)
async def upload_template(
    name: str = Form(..., min_length=2, max_length=160),
    description: str | None = Form(default=None),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    filename = file.filename or ""
    content = await file.read()
    with uow:
        ensure_admin_can_manage_imports(uow, user)
        return DocumentsAdminService.upload_template(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            name=name,
            description=description,
            filename=filename,
            content=content,
        )


@router.patch("/templates/{template_id}", response_model=DocumentTemplateDTO)
def update_template(
    template_id: UUID,
    body: DocumentTemplateUpdateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_manage_imports(uow, user)
        return DocumentsAdminService.update_template(
            uow,
            company_id=user.company_id,
            template_id=template_id,
            is_active=body.is_active,
        )


@router.get("/templates/{template_id}/download")
def download_template(
    template_id: UUID,
    request: Request,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        template = uow.documents.get_template(
            company_id=user.company_id,
            template_id=template_id,
        )
        if template is None:
            raise NotFound("Document template not found")

        obj = StorageService.get_object_stream(
            bucket=settings.MINIO_BUCKET,
            object_key=template.object_key,
        )
        uow.file_download_events.add(
            FileDownloadEventORM(
                company_id=user.company_id,
                source="ADMIN_DOCUMENT_TEMPLATE",
                token=None,
                object_key=template.object_key,
                bucket=settings.MINIO_BUCKET,
                mime_type=template.mime_type,
                file_name=template.source_filename,
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                actor_user_id=user.id,
                correlation_id=template.id,
            )
        )
        headers = {
            "Content-Disposition": f'attachment; filename="{template.source_filename}"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        }

        def gen():
            try:
                while True:
                    chunk = obj.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    obj.close()
                except Exception:
                    pass
                try:
                    obj.release_conn()
                except Exception:
                    pass

        return StreamingResponse(
            gen(),
            media_type=template.mime_type,
            headers=headers,
        )


@router.get(
    "/projects/{project_id}/context",
    response_model=ProjectDocumentContextResponse,
)
def project_context(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return DocumentsAdminService.project_context(
            uow,
            company_id=user.company_id,
            project_id=project_id,
        )


@router.post(
    "/projects/{project_id}/render",
    response_model=DocumentGenerationDTO,
)
def render_project_document(
    project_id: UUID,
    body: RenderProjectDocumentBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_manage_imports(uow, user)
        return DocumentsAdminService.render_for_project(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            project_id=project_id,
            template_id=body.template_id,
            overrides=body.overrides,
        )


@router.get("/generated", response_model=DocumentGenerationsResponse)
def list_generated_documents(
    project_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return DocumentsAdminService.list_generations(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            limit=limit,
        )


@router.get("/generated/{generation_id}/download")
def download_generated_document(
    generation_id: UUID,
    request: Request,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        generation = uow.documents.get_generation(
            company_id=user.company_id,
            generation_id=generation_id,
        )
        if generation is None:
            raise NotFound("Generated document not found")

        obj = StorageService.get_object_stream(
            bucket=settings.MINIO_BUCKET,
            object_key=generation.output_object_key,
        )
        uow.file_download_events.add(
            FileDownloadEventORM(
                company_id=user.company_id,
                source="ADMIN_DOCUMENT",
                token=None,
                object_key=generation.output_object_key,
                bucket=settings.MINIO_BUCKET,
                mime_type=generation.mime_type,
                file_name=generation.file_name,
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                actor_user_id=user.id,
                correlation_id=generation.id,
            )
        )
        headers = {
            "Content-Disposition": f'attachment; filename="{generation.file_name}"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        }

        def gen():
            try:
                while True:
                    chunk = obj.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    obj.close()
                except Exception:
                    pass
                try:
                    obj.release_conn()
                except Exception:
                    pass

        return StreamingResponse(
            gen(),
            media_type=generation.mime_type,
            headers=headers,
        )
