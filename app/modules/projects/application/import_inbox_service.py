"""Document import inbox (plan: "automation of factory documents").

A factory file reaches the inbox from an upload without a chosen project, a watched
folder or a mailbox. The service stores the file, parses it with the existing
import parsers, matches the project (order numbers already known on doors, the
project code or name in the file name), runs the existing analysis and, when the
company policy allows and the file is clean, runs the existing import. Everything
else waits for one decision in the office: pick a project, allow a partial import
or dismiss. Nothing bypasses the door import service, its idempotency or its audit.
"""
from __future__ import annotations

import base64
import hashlib
import re
import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import distinct, select

from app.core.config import settings
from app.integrations.storage.storage_service import StorageService
from app.modules.audit.application.service import AuditService
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.projects.application.file_import_service import (
    ProjectFileImportService,
    _build_alias_groups,
    _detect_mapping_profile,
    _first_value,
    _normalize_token,
    _parse_rows_by_filename,
)
from app.modules.projects.infrastructure.models import ImportInboxItemORM, ProjectORM
from app.shared.domain.errors import Conflict, NotFound, ValidationError
from app.shared.infrastructure.db.base import utcnow

SUPPORTED_EXTENSIONS = {"xlsx", "csv", "txt", "tsv", "json", "xml", "pdf"}
OPEN_STATUSES = {"NEW", "ANALYZED", "NEEDS_PROJECT", "FAILED"}


def _detail(exc: HTTPException) -> str:
    detail = exc.detail
    return (detail if isinstance(detail, str) else str(detail))[:500]


def _summary(result: dict) -> dict:
    diagnostics = result.get("diagnostics") or {}
    return {
        "mode": result.get("mode"),
        "parsed_rows": result.get("parsed_rows", 0),
        "prepared_rows": result.get("prepared_rows", 0),
        "would_import": result.get("would_import", 0),
        "would_skip": result.get("would_skip", 0),
        "imported": result.get("imported", 0),
        "skipped": result.get("skipped", 0),
        "errors": len(result.get("errors") or []),
        "first_errors": [{"row": e.get("row"), "message": str(e.get("message", ""))[:200]} for e in (result.get("errors") or [])[:5]],
        "missing_required_fields": list(diagnostics.get("missing_required_fields") or []),
        "mapping_profile": diagnostics.get("mapping_profile"),
        "idempotency_hit": bool(result.get("idempotency_hit")),
    }


class ImportInboxService:
    # ---- policy ------------------------------------------------------------------------------------
    @staticmethod
    def auto_commit_enabled(uow, company_id: uuid.UUID) -> bool:
        company = uow.session.get(CompanyORM, company_id)
        return bool(company is not None and getattr(company, "import_auto_commit", True))

    @staticmethod
    def set_auto_commit(uow, *, company_id: uuid.UUID, actor_user_id: uuid.UUID, enabled: bool) -> bool:
        company = uow.session.get(CompanyORM, company_id)
        if company is None:
            raise NotFound("Company not found")
        before = bool(company.import_auto_commit)
        company.import_auto_commit = bool(enabled)
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id, entity_type="company", entity_id=company_id,
                         action="IMPORT_INBOX_POLICY", before={"import_auto_commit": before}, after={"import_auto_commit": bool(enabled)})
        return bool(enabled)

    # ---- reads -------------------------------------------------------------------------------------
    @staticmethod
    def list_items(uow, *, company_id: uuid.UUID, status: str | None = None, limit: int = 50, offset: int = 0) -> list[ImportInboxItemORM]:
        stmt = select(ImportInboxItemORM).where(ImportInboxItemORM.company_id == company_id)
        if status:
            stmt = stmt.where(ImportInboxItemORM.status == status)
        return list(uow.session.scalars(stmt.order_by(ImportInboxItemORM.created_at.desc(), ImportInboxItemORM.id.desc())
                                        .offset(offset).limit(limit)).all())

    @staticmethod
    def get(uow, *, company_id: uuid.UUID, item_id: uuid.UUID) -> ImportInboxItemORM:
        item = uow.session.scalar(select(ImportInboxItemORM).where(ImportInboxItemORM.company_id == company_id, ImportInboxItemORM.id == item_id))
        if item is None:
            raise NotFound("Inbox item not found", details={"item_id": str(item_id)})
        return item

    @staticmethod
    def project_names(uow, *, company_id: uuid.UUID, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not project_ids:
            return {}
        rows = uow.session.execute(select(ProjectORM.id, ProjectORM.name).where(ProjectORM.company_id == company_id, ProjectORM.id.in_(project_ids))).all()
        return {row.id: row.name for row in rows}

    # ---- ingest ------------------------------------------------------------------------------------
    @staticmethod
    def ingest(uow, *, company_id: uuid.UUID, actor_user_id: uuid.UUID | None, filename: str, content: bytes,
               source: str = "UPLOAD", source_ref: str | None = None, project_id: uuid.UUID | None = None) -> tuple[ImportInboxItemORM, bool]:
        """Store, parse, match, analyze and (policy permitting) import. Returns (item, created)."""
        clean_name = re.sub(r"[^\w.\- ()Ѐ-ӿ֐-׿]", "_", (filename or "").strip())[:255] or "document"
        ext = clean_name.rsplit(".", 1)[-1].lower() if "." in clean_name else ""
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValidationError(f"unsupported file format: .{ext or 'unknown'}", field="file")
        if not content:
            raise ValidationError("file is empty", field="file")
        if len(content) > 20 * 1024 * 1024:
            raise ValidationError("file is too large (max 20MB)", field="file")
        sha = hashlib.sha256(content).hexdigest()
        existing = uow.session.scalar(select(ImportInboxItemORM).where(ImportInboxItemORM.company_id == company_id, ImportInboxItemORM.content_sha256 == sha))
        if existing is not None:
            # The same document again (a second upload, the folder and the mailbox): one inbox item, no second import.
            return existing, False
        item_id = uuid.uuid4()
        object_key = f"import-inbox/{company_id}/{item_id}/{clean_name}"
        StorageService.put_object(object_key=object_key, content=content, content_type="application/octet-stream")
        now = utcnow()
        item = ImportInboxItemORM(id=item_id, company_id=company_id, source=source, source_ref=(source_ref or None) and source_ref[:255],
                                  filename=clean_name, content_sha256=sha, object_key=object_key, status="NEW",
                                  created_by_user_id=actor_user_id, created_at=now, updated_at=now)
        uow.session.add(item)
        uow.session.flush()
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id, entity_type="import_inbox", entity_id=item.id,
                         action="IMPORT_INBOX_RECEIVED", after={"source": source, "filename": clean_name, "size": len(content)})

        # Parse with the existing parsers to learn the profile and the order numbers (no project needed yet).
        try:
            alias_groups = _build_alias_groups("auto_v1")
            rows = _parse_rows_by_filename(filename=clean_name, content=content, delimiter=None, alias_groups=alias_groups)
            profile = _detect_mapping_profile("auto_v1", rows) if rows else "auto_v1"
            alias_groups = _build_alias_groups(profile)
            orders = sorted({str(value).strip() for row in rows for value in [_first_value(row, alias_groups["order_number"])] if value and str(value).strip()})
        except HTTPException as exc:
            item.status = "FAILED"
            item.error = _detail(exc)
            return item, True
        item.detected_profile = profile
        item.order_numbers = orders[:50]

        if project_id is not None:
            project = uow.projects.get(company_id=company_id, project_id=project_id)
            if project is None:
                raise NotFound("Project not found", details={"project_id": str(project_id)})
            item.matched_project_id, item.match_reason = project.id, "MANUAL"
        else:
            matches = ImportInboxService._match_projects(uow, company_id=company_id, filename=clean_name, orders=orders)
            if len(matches) == 1:
                item.matched_project_id, item.match_reason = matches[0][0].id, matches[0][1]
            else:
                item.status = "NEEDS_PROJECT"
                item.candidate_project_ids = [str(project.id) for project, _ in matches[:5]]
                return item, True
        ImportInboxService._analyze(uow, item, actor_user_id=actor_user_id)
        return item, True

    @staticmethod
    def _match_projects(uow, *, company_id: uuid.UUID, filename: str, orders: list[str]) -> list[tuple[ProjectORM, str]]:
        """The project the document belongs to: known order numbers first, then the code or the name in the file name."""
        active = list(uow.session.scalars(select(ProjectORM).where(ProjectORM.company_id == company_id, ProjectORM.deleted_at.is_(None))).all())
        if orders:
            ids = list(uow.session.scalars(select(distinct(DoorORM.project_id)).where(
                DoorORM.company_id == company_id, DoorORM.order_number.in_(orders))).all())
            hits = [project for project in active if project.id in set(ids)]
            if hits:
                return [(project, "ORDER_NUMBER") for project in hits]
        name_blob = _normalize_token(filename)
        order_blob = " ".join(_normalize_token(order) for order in orders)
        by_code = [project for project in active if project.code and _normalize_token(project.code)
                   and (_normalize_token(project.code) in name_blob or _normalize_token(project.code) in order_blob)]
        if len(by_code) == 1:
            return [(by_code[0], "PROJECT_CODE")]
        by_name = [project for project in active if project.name and len(project.name.strip()) >= 4 and _normalize_token(project.name) in name_blob]
        if len(by_name) == 1:
            return [(by_name[0], "PROJECT_NAME")]
        return [(project, "PROJECT_CODE") for project in by_code] or [(project, "PROJECT_NAME") for project in by_name]

    # ---- analysis and import through the existing door import service ---------------------------
    @staticmethod
    def _run(uow, item: ImportInboxItemORM, *, analyze_only: bool, allow_partial: bool) -> dict:
        content = StorageService.get_object_bytes(bucket=settings.MINIO_BUCKET, object_key=item.object_key)
        return ProjectFileImportService.import_project_doors_from_file(
            uow, company_id=item.company_id, project_id=item.matched_project_id, filename=item.filename,
            content_base64=base64.b64encode(content).decode("ascii"), default_door_type_id=None, default_our_price=Decimal("0"),
            delimiter=None, mapping_profile=item.detected_profile or "auto_v1", strict_required_fields=None,
            create_missing_door_types=True, analyze_only=analyze_only, allow_partial_import=allow_partial,
        )

    @staticmethod
    def _analyze(uow, item: ImportInboxItemORM, *, actor_user_id: uuid.UUID | None) -> None:
        try:
            result = ImportInboxService._run(uow, item, analyze_only=True, allow_partial=False)
        except HTTPException as exc:
            item.status, item.error = "FAILED", _detail(exc)
            return
        summary = _summary(result)
        item.analysis = summary
        item.status = "ANALYZED"
        clean = summary["errors"] == 0 and not summary["missing_required_fields"] and summary["prepared_rows"] > 0
        if clean and ImportInboxService.auto_commit_enabled(uow, item.company_id):
            ImportInboxService.commit(uow, item, actor_user_id=actor_user_id, auto=True)

    @staticmethod
    def commit(uow, item: ImportInboxItemORM, *, actor_user_id: uuid.UUID | None, project_id: uuid.UUID | None = None,
               allow_partial: bool = False, auto: bool = False) -> ImportInboxItemORM:
        if item.status in {"IMPORTED", "DISMISSED"}:
            raise Conflict(f"Inbox item is already {item.status.lower()}")
        if project_id is not None:
            project = uow.projects.get(company_id=item.company_id, project_id=project_id)
            if project is None:
                raise NotFound("Project not found", details={"project_id": str(project_id)})
            item.matched_project_id, item.match_reason = project.id, "MANUAL"
        if item.matched_project_id is None:
            raise ValidationError("Choose the project for this document first", field="project_id")
        try:
            result = ImportInboxService._run(uow, item, analyze_only=False, allow_partial=allow_partial)
        except HTTPException as exc:
            if not allow_partial and (item.analysis or {}).get("errors"):
                # The import service refused the whole file because of row errors; the office may allow a partial import.
                item.status, item.error = "ANALYZED", _detail(exc)
                return item
            item.status, item.error = "FAILED", _detail(exc)
            AuditService.add(uow, company_id=item.company_id, actor_user_id=actor_user_id, entity_type="import_inbox", entity_id=item.id,
                             action="IMPORT_INBOX_FAILED", after={"source": item.source, "project_id": str(item.matched_project_id), "error": item.error, "auto": auto})
            return item
        summary = _summary(result)
        item.import_result = summary
        item.status = "IMPORTED"
        item.error = None
        item.decided_by_user_id = actor_user_id
        item.decided_at = utcnow()
        AuditService.add(uow, company_id=item.company_id, actor_user_id=actor_user_id, entity_type="import_inbox", entity_id=item.id,
                         action="IMPORT_INBOX_AUTO_IMPORTED" if auto else "IMPORT_INBOX_IMPORTED",
                         after={"source": item.source, "project_id": str(item.matched_project_id), "match_reason": item.match_reason, "imported": summary["imported"],
                                "skipped": summary["skipped"], "errors": summary["errors"], "allow_partial": allow_partial})
        return item

    @staticmethod
    def dismiss(uow, item: ImportInboxItemORM, *, actor_user_id: uuid.UUID) -> ImportInboxItemORM:
        if item.status == "IMPORTED":
            raise Conflict("An imported document cannot be dismissed")
        item.status = "DISMISSED"
        item.decided_by_user_id = actor_user_id
        item.decided_at = utcnow()
        AuditService.add(uow, company_id=item.company_id, actor_user_id=actor_user_id, entity_type="import_inbox", entity_id=item.id,
                         action="IMPORT_INBOX_DISMISSED", after={"source": item.source, "filename": item.filename})
        return item
