from __future__ import annotations

import html
import mimetypes
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import date
from io import BytesIO
from pathlib import PurePosixPath

from app.core.config import settings
from app.integrations.storage.storage_service import StorageService
from app.modules.documents.infrastructure.models import (
    DocumentGenerationORM,
    DocumentTemplateORM,
)
from app.modules.doors.domain.enums import DoorStatus
from app.shared.domain.errors import NotFound, ValidationError


PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")
MAX_TEMPLATE_BYTES = 10 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".docx", ".html", ".htm", ".txt"}
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_TEXT_TAG = f"{{{WORD_NS}}}t"
WORD_PARAGRAPH_TAG = f"{{{WORD_NS}}}p"

ET.register_namespace("w", WORD_NS)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "document"


def _file_extension(filename: str) -> str:
    name = filename.strip().lower()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]


def _sanitize_filename(filename: str) -> str:
    basename = PurePosixPath(filename.replace("\\", "/")).name.strip()
    basename = re.sub(r"[^A-Za-z0-9_. -]+", "_", basename)
    return basename[:180] or "template.txt"


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError("Template text must be UTF-8 or CP1251 encoded")


def _extract_docx_placeholders(content: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            found: set[str] = set()
            for name in zf.namelist():
                if not name.startswith("word/") or not name.endswith(".xml"):
                    continue
                xml = zf.read(name)
                text = xml.decode("utf-8", "ignore")
                found.update(PLACEHOLDER_RE.findall(text))
                found.update(_extract_docx_placeholders_from_xml(xml))
            return sorted(found)
    except zipfile.BadZipFile as exc:
        raise ValidationError("Invalid DOCX template") from exc


def _extract_docx_placeholders_from_xml(xml: bytes) -> set[str]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return set()

    found: set[str] = set()
    for paragraph in root.iter(WORD_PARAGRAPH_TAG):
        combined = "".join(node.text or "" for node in paragraph.iter(WORD_TEXT_TAG))
        found.update(PLACEHOLDER_RE.findall(combined))
    return found


def extract_placeholders(*, filename: str, content: bytes) -> list[str]:
    ext = _file_extension(filename)
    if ext == ".docx":
        return _extract_docx_placeholders(content)
    return sorted(set(PLACEHOLDER_RE.findall(_decode_text(content))))


def _replace_placeholders(text: str, values: dict[str, object], *, escape_xml: bool, escape_html: bool) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key, "")
        rendered = "" if value is None else str(value)
        if escape_xml:
            return html.escape(rendered, quote=True)
        if escape_html:
            return html.escape(rendered, quote=False)
        return rendered

    return PLACEHOLDER_RE.sub(repl, text)


def _render_docx(content: bytes, values: dict[str, object]) -> bytes:
    try:
        source = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValidationError("Invalid DOCX template") from exc

    out = BytesIO()
    with source, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                data = _render_docx_xml(data, values)
            target.writestr(item, data)
    return out.getvalue()


def _render_docx_xml(data: bytes, values: dict[str, object]) -> bytes:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        text = data.decode("utf-8", "ignore")
        return _replace_placeholders(
            text,
            values,
            escape_xml=True,
            escape_html=False,
        ).encode("utf-8")

    changed = False
    for paragraph in root.iter(WORD_PARAGRAPH_TAG):
        text_nodes = list(paragraph.iter(WORD_TEXT_TAG))
        if not text_nodes:
            continue

        split_placeholder_possible = False
        for node in text_nodes:
            original = node.text or ""
            replaced = _replace_placeholders(
                original,
                values,
                escape_xml=False,
                escape_html=False,
            )
            if replaced != original:
                node.text = replaced
                changed = True
            if "{{" in original or "}}" in original:
                split_placeholder_possible = True

        combined = "".join(node.text or "" for node in text_nodes)
        if split_placeholder_possible and PLACEHOLDER_RE.search(combined):
            rendered = _replace_placeholders(
                combined,
                values,
                escape_xml=False,
                escape_html=False,
            )
            text_nodes[0].text = rendered
            for node in text_nodes[1:]:
                node.text = ""
            changed = True

    if not changed:
        return data
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def render_template_bytes(
    *,
    filename: str,
    content: bytes,
    values: dict[str, object],
) -> tuple[bytes, str]:
    ext = _file_extension(filename)
    if ext == ".docx":
        return _render_docx(content, values), (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    text = _decode_text(content)
    rendered = _replace_placeholders(
        text,
        values,
        escape_xml=False,
        escape_html=ext in {".html", ".htm"},
    )
    mime = "text/html; charset=utf-8" if ext in {".html", ".htm"} else "text/plain; charset=utf-8"
    return rendered.encode("utf-8"), mime


def _missing_placeholder_keys(
    placeholders: list[str] | None,
    values: dict[str, object],
) -> list[str]:
    return [placeholder for placeholder in placeholders or [] if placeholder not in values]


class DocumentsAdminService:
    @staticmethod
    def _ensure_unique_code(uow, *, company_id: uuid.UUID, name: str) -> str:
        base = _slugify(name)
        candidate = base
        counter = 2
        while uow.documents.get_template_by_code(company_id=company_id, code=candidate):
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    @staticmethod
    def _template_payload(row: DocumentTemplateORM) -> dict:
        return {
            "id": str(row.id),
            "code": row.code,
            "name": row.name,
            "description": row.description,
            "entity_scope": row.entity_scope,
            "source_filename": row.source_filename,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
            "placeholders": row.placeholders or [],
            "is_active": row.is_active,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _generation_payload(
        row: DocumentGenerationORM,
        *,
        template: DocumentTemplateORM | None = None,
        project=None,
    ) -> dict:
        return {
            "id": str(row.id),
            "template_id": str(row.template_id),
            "project_id": str(row.project_id),
            "template_name": template.name if template else None,
            "project_name": project.name if project else None,
            "project_code": project.code if project else None,
            "file_name": row.file_name,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
            "status": row.status,
            "download_url": f"/api/v1/admin/documents/generated/{row.id}/download",
            "created_at": row.created_at,
        }

    @staticmethod
    def list_templates(uow, *, company_id: uuid.UUID) -> dict:
        rows = uow.documents.list_templates(company_id=company_id)
        return {"items": [DocumentsAdminService._template_payload(row) for row in rows]}

    @staticmethod
    def update_template(
        uow,
        *,
        company_id: uuid.UUID,
        template_id: uuid.UUID,
        is_active: bool | None = None,
    ) -> dict:
        row = uow.documents.get_template(
            company_id=company_id,
            template_id=template_id,
        )
        if row is None:
            raise NotFound("Document template not found")
        if is_active is not None:
            row.is_active = is_active
        uow.session.flush()
        return DocumentsAdminService._template_payload(row)

    @staticmethod
    def upload_template(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        name: str,
        description: str | None,
        filename: str,
        content: bytes,
    ) -> dict:
        clean_name = name.strip()
        if len(clean_name) < 2:
            raise ValidationError("Template name is required")
        if not content:
            raise ValidationError("Template file is empty")
        if len(content) > MAX_TEMPLATE_BYTES:
            raise ValidationError("Template file is too large (max 10MB)")

        source_filename = _sanitize_filename(filename)
        ext = _file_extension(source_filename)
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValidationError("Unsupported template format")

        placeholders = extract_placeholders(filename=source_filename, content=content)
        mime = (
            mimetypes.guess_type(source_filename)[0]
            or "application/octet-stream"
        )
        template_id = uuid.uuid4()
        object_key = f"documents/{company_id}/templates/{template_id}/{source_filename}"
        StorageService.put_object(object_key=object_key, content=content, content_type=mime)

        row = DocumentTemplateORM(
            id=template_id,
            company_id=company_id,
            code=DocumentsAdminService._ensure_unique_code(
                uow,
                company_id=company_id,
                name=clean_name,
            ),
            name=clean_name,
            description=(description or "").strip() or None,
            source_filename=source_filename,
            object_key=object_key,
            mime_type=mime,
            size_bytes=len(content),
            placeholders=placeholders,
            uploaded_by_user_id=actor_user_id,
            is_active=True,
        )
        uow.documents.save_template(row)
        uow.session.flush()
        return DocumentsAdminService._template_payload(row)

    @staticmethod
    def project_context(uow, *, company_id: uuid.UUID, project_id: uuid.UUID) -> dict:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound("Project not found", details={"project_id": str(project_id)})
        company = uow.settings.get_by_id(company_id=company_id)
        doors = uow.doors.list_by_project(company_id=company_id, project_id=project_id)

        def count_status(status: DoorStatus) -> int:
            return sum(1 for door in doors if door.status == status)

        values: dict[str, object] = {
            "company.name": company.name if company else "",
            "project.id": str(project.id),
            "project.code": project.code or "",
            "project.name": project.name,
            "project.address": project.address,
            "project.developer_company": project.developer_company or "",
            "project.contact_name": project.contact_name or "",
            "project.contact_phone": project.contact_phone or "",
            "project.contact_email": project.contact_email or "",
            "project.planned_start_date": project.planned_start_date.isoformat()
            if project.planned_start_date
            else "",
            "project.planned_end_date": project.planned_end_date.isoformat()
            if project.planned_end_date
            else "",
            "doors.total": len(doors),
            "doors.installed": count_status(DoorStatus.INSTALLED),
            "doors.in_progress": count_status(DoorStatus.IN_PROGRESS),
            "doors.not_installed": count_status(DoorStatus.NOT_INSTALLED),
            "doors.locked": count_status(DoorStatus.LOCKED),
            "doors.issues": count_status(DoorStatus.ISSUE_OPEN),
            "date.today": date.today().isoformat(),
        }
        return {"project_id": str(project_id), "fields": values}

    @staticmethod
    def render_for_project(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        project_id: uuid.UUID,
        template_id: uuid.UUID,
        overrides: dict[str, object] | None = None,
    ) -> dict:
        template = uow.documents.get_template(
            company_id=company_id,
            template_id=template_id,
        )
        if not template or not template.is_active:
            raise NotFound("Document template not found")

        context = DocumentsAdminService.project_context(
            uow,
            company_id=company_id,
            project_id=project_id,
        )["fields"]
        values = {**context, **(overrides or {})}
        missing_placeholders = _missing_placeholder_keys(
            template.placeholders,
            values,
        )
        if missing_placeholders:
            raise ValidationError(
                "Document template has unresolved placeholders",
                details={"missing_placeholders": missing_placeholders},
            )
        source = StorageService.get_object_bytes(
            bucket=settings.MINIO_BUCKET,
            object_key=template.object_key,
        )
        rendered, output_mime = render_template_bytes(
            filename=template.source_filename,
            content=source,
            values=values,
        )
        stem = template.source_filename.rsplit(".", 1)[0]
        ext = _file_extension(template.source_filename) or ".txt"
        generation_id = uuid.uuid4()
        file_name = f"{_slugify(stem)}-{generation_id.hex[:8]}{ext}"
        output_key = f"documents/{company_id}/projects/{project_id}/generated/{generation_id}/{file_name}"
        StorageService.put_object(
            object_key=output_key,
            content=rendered,
            content_type=output_mime,
        )
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        row = DocumentGenerationORM(
            id=generation_id,
            company_id=company_id,
            template_id=template.id,
            project_id=project_id,
            output_object_key=output_key,
            file_name=file_name,
            mime_type=output_mime,
            size_bytes=len(rendered),
            field_values=values,
            rendered_by_user_id=actor_user_id,
            status="READY",
        )
        uow.documents.save_generation(row)
        uow.session.flush()
        return DocumentsAdminService._generation_payload(
            row,
            template=template,
            project=project,
        )

    @staticmethod
    def list_generations(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> dict:
        rows = uow.documents.list_generations(
            company_id=company_id,
            project_id=project_id,
            limit=limit,
        )
        items = []
        for row in rows:
            template = uow.documents.get_template(
                company_id=company_id,
                template_id=row.template_id,
            )
            project = uow.projects.get(company_id=company_id, project_id=row.project_id)
            items.append(
                DocumentsAdminService._generation_payload(
                    row,
                    template=template,
                    project=project,
                )
            )
        return {"items": items}
