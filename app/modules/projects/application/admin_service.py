from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation

from app.modules.audit.application.service import AuditService
from app.modules.companies.application.alerts_service import CompanyLimitAlertsService
from app.modules.companies.domain.errors import CompanyPlanLimitExceeded
from app.modules.projects.api.schemas import (
    FailedImportRunsQueueResponse,
    ProjectLatestImportReviewResponse,
    ProjectBulkImportReconcileResponse,
    ImportDoorsFromFileResponse,
    ImportDoorsResponse,
    ProjectCreateResponse,
    ProjectBulkImportReconcileItemDTO,
    RetryFailedImportRunsResponse,
    RetryFailedImportRunItemDTO,
    ProjectImportRunsResponse,
)
from app.modules.projects.application.file_import_service import (
    ProjectFileImportService,
)
from app.modules.projects.application.use_cases import ProjectUseCases
from app.modules.projects.infrastructure.models import ProjectImportRunORM
from app.shared.domain.errors import NotFound, ValidationError
from app.shared.infrastructure.observability import get_logger, log_event


logger = get_logger(__name__)


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _order_number_matches(value: str | None, query: str | None) -> bool:
    q = _empty_to_none(query)
    if q is None:
        return True
    target = _empty_to_none(value)
    if target is None:
        return False
    return q.casefold() in target.casefold()


def _floor_sort_key(value: str | None) -> tuple[int, int, str]:
    if not value:
        return (1, 0, "")
    match = re.search(r"-?\d+", value)
    if match is not None:
        return (0, int(match.group(0)), value.casefold())
    return (0, 0, value.casefold())


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _audit_import_diagnostics(diagnostics: dict | None) -> dict | None:
    if not isinstance(diagnostics, dict):
        return None
    required_fields: list[dict] = []
    for item in (diagnostics.get("required_fields") or [])[:20]:
        if not isinstance(item, dict):
            continue
        required_fields.append(
            {
                "field_key": str(item.get("field_key") or "")[:64],
                "display_name": str(item.get("display_name") or "")[:120],
                "found": bool(item.get("found")),
                "matched_columns": [
                    str(x)[:120]
                    for x in (item.get("matched_columns") or [])[:10]
                ],
            }
        )
    data_summary = diagnostics.get("data_summary")
    sanitized_data_summary = None
    if isinstance(data_summary, dict):
        sanitized_data_summary = {
            "source_rows": _safe_int(data_summary.get("source_rows"), 0),
            "prepared_rows": _safe_int(data_summary.get("prepared_rows"), 0),
            "rows_with_errors": _safe_int(data_summary.get("rows_with_errors"), 0),
            "duplicate_rows_skipped": _safe_int(
                data_summary.get("duplicate_rows_skipped"), 0
            ),
            "unique_order_numbers": _safe_int(
                data_summary.get("unique_order_numbers"), 0
            ),
            "unique_houses": _safe_int(data_summary.get("unique_houses"), 0),
            "unique_floors": _safe_int(data_summary.get("unique_floors"), 0),
            "unique_apartments": _safe_int(
                data_summary.get("unique_apartments"), 0
            ),
            "unique_locations": _safe_int(data_summary.get("unique_locations"), 0),
            "unique_markings": _safe_int(data_summary.get("unique_markings"), 0),
        }
    preview_groups: list[dict] = []
    for item in (diagnostics.get("preview_groups") or [])[:80]:
        if not isinstance(item, dict):
            continue
        preview_groups.append(
            {
                "order_number": str(item.get("order_number") or "")[:80] or None,
                "house_number": str(item.get("house_number") or "")[:40] or None,
                "floor_label": str(item.get("floor_label") or "")[:40] or None,
                "apartment_number": str(item.get("apartment_number") or "")[:40]
                or None,
                "door_marking": str(item.get("door_marking") or "")[:120] or None,
                "door_count": _safe_int(item.get("door_count"), 0),
                "location_codes": [
                    str(x)[:80] for x in (item.get("location_codes") or [])[:10]
                ],
            }
        )
    return {
        "required_fields": required_fields,
        "recognized_columns": [
            str(x)[:120] for x in (diagnostics.get("recognized_columns") or [])[:80]
        ],
        "unmapped_columns": [
            str(x)[:120] for x in (diagnostics.get("unmapped_columns") or [])[:80]
        ],
        "mapping_profile": str(diagnostics.get("mapping_profile") or "")[:64] or None,
        "strict_required_fields": (
            bool(diagnostics.get("strict_required_fields"))
            if diagnostics.get("strict_required_fields") is not None
            else None
        ),
        "missing_required_fields": [
            str(x)[:64] for x in (diagnostics.get("missing_required_fields") or [])[:20]
        ],
        "data_summary": sanitized_data_summary,
        "preview_groups": preview_groups,
    }


def _audit_import_errors(errors: list | None) -> list[dict]:
    if not isinstance(errors, list):
        return []
    preview: list[dict] = []
    for item in errors[:20]:
        if not isinstance(item, dict):
            continue
        preview.append(
            {
                "row": _safe_int(item.get("row"), 0),
                "message": str(item.get("message") or "")[:300],
            }
        )
    return preview


def _audit_import_after(*, filename: str, data: dict) -> dict:
    mode = str(data.get("mode") or "import")
    errors = data.get("errors")
    return {
        "filename": filename[:255],
        "mode": mode,
        "parsed_rows": _safe_int(data.get("parsed_rows"), 0),
        "prepared_rows": _safe_int(data.get("prepared_rows"), 0),
        "imported": _safe_int(data.get("imported"), 0),
        "skipped": _safe_int(data.get("skipped"), 0),
        "would_import": _safe_int(data.get("would_import"), 0),
        "would_skip": _safe_int(data.get("would_skip"), 0),
        "idempotency_hit": bool(data.get("idempotency_hit")),
        "errors_count": len(errors) if isinstance(errors, list) else 0,
        "errors_preview": _audit_import_errors(errors),
        "diagnostics": _audit_import_diagnostics(data.get("diagnostics")),
    }


def _import_run_status(*, mode: str, imported: int, errors_count: int) -> str:
    if mode == "analyze":
        return "ANALYZED"
    if imported <= 0 and errors_count > 0:
        return "FAILED"
    if imported > 0 and errors_count > 0:
        return "PARTIAL"
    if imported > 0:
        return "SUCCESS"
    return "EMPTY"


def _public_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    return {
        key: value
        for key, value in payload.items()
        if not str(key).startswith("_")
    }


def _retry_prepared_rows(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    retry_section = payload.get("_retry")
    if not isinstance(retry_section, dict):
        return []
    prepared = retry_section.get("prepared_rows")
    if not isinstance(prepared, list):
        return []
    return [row for row in prepared if isinstance(row, dict)]


def _deserialize_retry_rows(prepared_rows: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for row in prepared_rows:
        door_type_id_raw = str(row.get("door_type_id") or "").strip()
        unit_label = str(row.get("unit_label") or "").strip()
        price_raw = str(row.get("our_price") or "0").strip()
        if not door_type_id_raw or not unit_label:
            continue
        try:
            door_type_id = uuid.UUID(door_type_id_raw)
        except ValueError:
            continue
        try:
            our_price = Decimal(price_raw)
        except InvalidOperation:
            continue
        rows.append(
            {
                "door_type_id": door_type_id,
                "unit_label": unit_label[:120],
                "our_price": our_price,
                "order_number": _empty_to_none(row.get("order_number")),
                "house_number": _empty_to_none(row.get("house_number")),
                "floor_label": _empty_to_none(row.get("floor_label")),
                "apartment_number": _empty_to_none(row.get("apartment_number")),
                "location_code": _empty_to_none(row.get("location_code")),
                "door_marking": _empty_to_none(row.get("door_marking")),
            }
        )
    return rows


def _build_retry_persist_payload(*, result: dict, run: ProjectImportRunORM) -> dict:
    payload = dict(result)
    retry_rows = _retry_prepared_rows(run.result_payload)
    payload["_retry"] = {
        "filename": run.source_filename,
        "mapping_profile": run.mapping_profile,
        "prepared_rows": retry_rows,
    }
    return payload


def _run_retry_import(
    uow,
    *,
    company_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    project_id: uuid.UUID,
    source_run: ProjectImportRunORM,
    audit_action: str,
) -> ImportDoorsFromFileResponse:
    prepared_rows = _deserialize_retry_rows(_retry_prepared_rows(source_run.result_payload))
    if not prepared_rows:
        raise ValidationError(
            "Retry data is unavailable for this import run",
            details={"run_id": str(source_run.id)},
        )

    try:
        imported, skipped_existing = ProjectUseCases.import_doors(
            uow,
            company_id=company_id,
            project_id=project_id,
            rows=prepared_rows,
            skip_existing=True,
        )
    except CompanyPlanLimitExceeded as e:
        AuditService.add_independent(
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="company_plan",
            entity_id=company_id,
            action="PLAN_LIMIT_BLOCK_DOOR_IMPORT",
            before=e.details or None,
            after={
                "requested": "doors_import_retry",
                "project_id": str(project_id),
                "run_id": str(source_run.id),
            },
        )
        raise

    source_payload = _public_payload(source_run.result_payload)
    result = {
        "parsed_rows": _safe_int(source_payload.get("parsed_rows"), len(prepared_rows)),
        "prepared_rows": len(prepared_rows),
        "imported": imported,
        "skipped": skipped_existing,
        "errors": [],
        "diagnostics": source_payload.get("diagnostics"),
        "mode": "import_retry",
        "would_import": imported,
        "would_skip": skipped_existing,
        "idempotency_hit": False,
    }
    retry_run = ProjectImportRunORM(
        company_id=company_id,
        project_id=project_id,
        fingerprint=f"retry:{source_run.id}:{uuid.uuid4().hex}",
        import_mode="import_retry",
        source_filename=source_run.source_filename,
        mapping_profile=source_run.mapping_profile or "auto_v1",
        result_payload=_build_retry_persist_payload(
            result=result,
            run=source_run,
        ),
    )
    uow.project_import_runs.save(retry_run)
    uow.session.flush()

    AuditService.add_independent(
        company_id=company_id,
        actor_user_id=actor_user_id,
        entity_type="project",
        entity_id=project_id,
        action=audit_action,
        after={
            **_audit_import_after(
                filename=source_run.source_filename or "retry",
                data=result,
            ),
            "source_run_id": str(source_run.id),
        },
    )
    if imported > 0:
        CompanyLimitAlertsService.evaluate_and_alert(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            metric_keys=["doors_per_project"],
        )
    log_event(
        logger,
        "project.import.retry_completed",
        company_id=company_id,
        project_id=project_id,
        actor_user_id=actor_user_id,
        source_run_id=source_run.id,
        retry_run_id=retry_run.id,
        imported=imported,
        skipped=skipped_existing,
    )
    return ImportDoorsFromFileResponse(**result)


def _to_import_run_item(run: ProjectImportRunORM) -> dict:
    payload = _public_payload(run.result_payload)
    mode = str(run.import_mode or "")
    imported = _safe_int(payload.get("imported"), 0)
    errors_count = _errors_count_from_payload(payload)
    last_error = _first_error_from_payload(payload)
    retry_available = mode in {"import", "import_retry"} and bool(
        _retry_prepared_rows(run.result_payload)
    )
    return {
        "id": run.id,
        "created_at": run.created_at,
        "mode": mode,
        "status": _import_run_status(
            mode=mode,
            imported=imported,
            errors_count=errors_count,
        ),
        "source_filename": run.source_filename,
        "mapping_profile": run.mapping_profile,
        "parsed_rows": _safe_int(payload.get("parsed_rows"), 0),
        "prepared_rows": _safe_int(payload.get("prepared_rows"), 0),
        "imported": imported,
        "skipped": _safe_int(payload.get("skipped"), 0),
        "errors_count": errors_count,
        "idempotency_hit": bool(payload.get("idempotency_hit")),
        "retry_available": retry_available,
        "last_error": last_error,
    }


def _to_import_run_details(run: ProjectImportRunORM) -> dict:
    item = _to_import_run_item(run)
    payload = _public_payload(run.result_payload)
    item.update(
        {
            "errors": _audit_import_errors(payload.get("errors")),
            "diagnostics": _audit_import_diagnostics(payload.get("diagnostics")),
            "would_import": _safe_int(payload.get("would_import"), 0),
            "would_skip": _safe_int(payload.get("would_skip"), 0),
        }
    )
    return item


def _errors_count_from_payload(payload: dict | None) -> int:
    if not isinstance(payload, dict):
        return 0
    errors_raw = payload.get("errors")
    if isinstance(errors_raw, list):
        return len(errors_raw)
    return _safe_int(payload.get("errors_count"), 0)


def _first_error_from_payload(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    errors_raw = payload.get("errors")
    if not isinstance(errors_raw, list) or not errors_raw:
        return None
    first = errors_raw[0]
    if isinstance(first, dict):
        text = str(first.get("message") or "").strip()
        return text[:300] or None
    if first is None:
        return None
    text = str(first).strip()
    return text[:300] or None


class ProjectAdminService:
    @staticmethod
    def list_import_mapping_profiles(*, company_id: uuid.UUID) -> dict:
        del company_id
        items = [
            {
                "code": "auto_v1",
                "name": "Auto Detect v1",
                "description": "Auto-detect columns and delimiter using multilingual aliases.",
                "preferred_delimiter": None,
            },
            {
                "code": "factory_he_v1",
                "name": "Factory Hebrew v1",
                "description": "Optimized for Hebrew factory exports (preferred delimiter ';', includes מספר הזמנה).",
                "preferred_delimiter": ";",
            },
            {
                "code": "factory_ru_v1",
                "name": "Factory RU v1",
                "description": "Optimized for Russian-labeled exports (preferred delimiter ';').",
                "preferred_delimiter": ";",
            },
            {
                "code": "generic_en_v1",
                "name": "Generic EN v1",
                "description": "Optimized for generic English CSV/TSV exports.",
                "preferred_delimiter": ",",
            },
        ]
        return {
            "default_code": "auto_v1",
            "items": items,
        }

    @staticmethod
    def list_projects(
        uow,
        *,
        company_id: uuid.UUID,
        q: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> dict:
        items = uow.projects.list(
            company_id=company_id,
            q=q,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [
                {
                    "id": p.id,
                    "name": p.name,
                    "address": p.address,
                    "status": _status_value(p.status),
                }
                for p in items
            ]
        }

    @staticmethod
    def import_runs_history(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        mode: str | None,
        limit: int,
        offset: int,
    ) -> ProjectImportRunsResponse:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found",
                details={"project_id": str(project_id)},
            )
        normalized_mode = mode.strip().lower() if mode else None
        if normalized_mode and normalized_mode not in {"analyze", "import", "import_retry"}:
            raise ValidationError("unsupported mode")
        rows = uow.project_import_runs.list(
            company_id=company_id,
            project_id=project_id,
            import_mode=normalized_mode,
            limit=limit,
            offset=offset,
        )
        return ProjectImportRunsResponse(items=[_to_import_run_item(row) for row in rows])

    @staticmethod
    def import_run_details(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> dict:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found",
                details={"project_id": str(project_id)},
            )
        run = uow.project_import_runs.get_by_id(
            company_id=company_id,
            project_id=project_id,
            run_id=run_id,
        )
        if run is None:
            raise NotFound(
                "Import run not found",
                details={"project_id": str(project_id), "run_id": str(run_id)},
            )
        return _to_import_run_details(run)

    @staticmethod
    def review_latest_imports(
        uow,
        *,
        company_id: uuid.UUID,
        project_ids: list[uuid.UUID],
        only_failed_runs: bool = False,
    ) -> ProjectLatestImportReviewResponse:
        items = []
        reviewable_projects = 0
        failed_or_partial_projects = 0
        skipped_projects = 0

        for project_id in project_ids:
            project = uow.projects.get(company_id=company_id, project_id=project_id)
            if project is None:
                skipped_projects += 1
                items.append(
                    {
                        "project_id": project_id,
                        "project_name": "Project not found",
                        "source_run_id": None,
                        "mode": None,
                        "status": "FAILED_PROJECT_NOT_FOUND",
                        "source_filename": None,
                        "mapping_profile": None,
                        "parsed_rows": 0,
                        "prepared_rows": 0,
                        "imported": 0,
                        "skipped": 0,
                        "errors_count": 1,
                        "last_error": "Project not found",
                        "retry_available": False,
                    }
                )
                continue

            source_run = uow.project_import_runs.latest_retryable_for_project(
                company_id=company_id,
                project_id=project_id,
            )
            if source_run is None:
                skipped_projects += 1
                items.append(
                    {
                        "project_id": project.id,
                        "project_name": project.name,
                        "source_run_id": None,
                        "mode": None,
                        "status": "SKIPPED_NO_RUN",
                        "source_filename": None,
                        "mapping_profile": None,
                        "parsed_rows": 0,
                        "prepared_rows": 0,
                        "imported": 0,
                        "skipped": 0,
                        "errors_count": 0,
                        "last_error": None,
                        "retry_available": False,
                    }
                )
                continue

            payload = _public_payload(source_run.result_payload)
            imported = _safe_int(payload.get("imported"), 0)
            errors_count = _errors_count_from_payload(payload)
            status = _import_run_status(
                mode=str(source_run.import_mode or ""),
                imported=imported,
                errors_count=errors_count,
            )
            if status in {"FAILED", "PARTIAL"}:
                failed_or_partial_projects += 1

            if only_failed_runs and status not in {"FAILED", "PARTIAL"}:
                skipped_projects += 1
                items.append(
                    {
                        "project_id": project.id,
                        "project_name": project.name,
                        "source_run_id": source_run.id,
                        "mode": str(source_run.import_mode or ""),
                        "status": "SKIPPED_NOT_FAILED",
                        "source_filename": source_run.source_filename,
                        "mapping_profile": source_run.mapping_profile,
                        "parsed_rows": _safe_int(payload.get("parsed_rows"), 0),
                        "prepared_rows": _safe_int(payload.get("prepared_rows"), 0),
                        "imported": imported,
                        "skipped": _safe_int(payload.get("skipped"), 0),
                        "errors_count": errors_count,
                        "last_error": _first_error_from_payload(payload),
                        "retry_available": bool(_retry_prepared_rows(source_run.result_payload)),
                    }
                )
                continue

            reviewable_projects += 1
            items.append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "source_run_id": source_run.id,
                    "mode": str(source_run.import_mode or ""),
                    "status": status,
                    "source_filename": source_run.source_filename,
                    "mapping_profile": source_run.mapping_profile,
                    "parsed_rows": _safe_int(payload.get("parsed_rows"), 0),
                    "prepared_rows": _safe_int(payload.get("prepared_rows"), 0),
                    "imported": imported,
                    "skipped": _safe_int(payload.get("skipped"), 0),
                    "errors_count": errors_count,
                    "last_error": _first_error_from_payload(payload),
                    "retry_available": bool(_retry_prepared_rows(source_run.result_payload)),
                }
            )

        return ProjectLatestImportReviewResponse(
            items=items,
            total_projects=len(project_ids),
            reviewable_projects=reviewable_projects,
            failed_or_partial_projects=failed_or_partial_projects,
            skipped_projects=skipped_projects,
        )

    @staticmethod
    def retry_import_run(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> ImportDoorsFromFileResponse:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found",
                details={"project_id": str(project_id)},
            )
        run = uow.project_import_runs.get_by_id(
            company_id=company_id,
            project_id=project_id,
            run_id=run_id,
        )
        if run is None:
            raise NotFound(
                "Import run not found",
                details={"project_id": str(project_id), "run_id": str(run_id)},
            )
        return _run_retry_import(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
            source_run=run,
            audit_action="PROJECT_DOORS_IMPORT_RETRY",
        )

    @staticmethod
    def failed_import_runs_queue(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> FailedImportRunsQueueResponse:
        rows, total = uow.project_import_runs.failed_queue(
            company_id=company_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        items = []
        for run, project in rows:
            payload = _public_payload(run.result_payload)
            imported = _safe_int(payload.get("imported"), 0)
            errors_count = _errors_count_from_payload(payload)
            items.append(
                {
                    "run_id": run.id,
                    "project_id": run.project_id,
                    "project_name": (
                        project.name
                        if project is not None and getattr(project, "name", None)
                        else str(run.project_id)
                    ),
                    "created_at": run.created_at,
                    "mode": str(run.import_mode or ""),
                    "status": _import_run_status(
                        mode=str(run.import_mode or ""),
                        imported=imported,
                        errors_count=errors_count,
                    ),
                    "source_filename": run.source_filename,
                    "mapping_profile": run.mapping_profile,
                    "parsed_rows": _safe_int(payload.get("parsed_rows"), 0),
                    "prepared_rows": _safe_int(payload.get("prepared_rows"), 0),
                    "imported": imported,
                    "skipped": _safe_int(payload.get("skipped"), 0),
                    "errors_count": errors_count,
                    "last_error": _first_error_from_payload(payload),
                    "retry_available": bool(_retry_prepared_rows(run.result_payload)),
                }
            )
        return FailedImportRunsQueueResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def retry_failed_runs_bulk(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        run_ids: list[uuid.UUID],
    ) -> RetryFailedImportRunsResponse:
        unique_run_ids = list(dict.fromkeys(run_ids))
        runs = uow.project_import_runs.list_by_ids(
            company_id=company_id,
            run_ids=unique_run_ids,
        )
        run_by_id = {run.id: run for run in runs}
        items: list[RetryFailedImportRunItemDTO] = []
        successful_runs = 0
        failed_runs = 0
        skipped_runs = 0

        for run_id in unique_run_ids:
            run = run_by_id.get(run_id)
            if run is None:
                failed_runs += 1
                items.append(
                    RetryFailedImportRunItemDTO(
                        run_id=run_id,
                        project_id=None,
                        status="FAILED_RUN_NOT_FOUND",
                        imported=0,
                        skipped=0,
                        errors_count=1,
                        last_error="Import run not found",
                    )
                )
                continue

            mode = str(run.import_mode or "")
            if mode not in {"import", "import_retry"}:
                skipped_runs += 1
                items.append(
                    RetryFailedImportRunItemDTO(
                        run_id=run.id,
                        project_id=run.project_id,
                        status="SKIPPED_UNSUPPORTED_MODE",
                        imported=0,
                        skipped=0,
                        errors_count=0,
                        last_error=None,
                    )
                )
                continue

            payload = _public_payload(run.result_payload)
            source_status = _import_run_status(
                mode=mode,
                imported=_safe_int(payload.get("imported"), 0),
                errors_count=_errors_count_from_payload(payload),
            )
            if source_status not in {"FAILED", "PARTIAL"}:
                skipped_runs += 1
                items.append(
                    RetryFailedImportRunItemDTO(
                        run_id=run.id,
                        project_id=run.project_id,
                        status="SKIPPED_NOT_FAILED",
                        imported=0,
                        skipped=0,
                        errors_count=0,
                        last_error=None,
                    )
                )
                continue

            try:
                result = _run_retry_import(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    project_id=run.project_id,
                    source_run=run,
                    audit_action="PROJECT_DOORS_IMPORT_RETRY_BULK",
                )
            except Exception as e:
                failed_runs += 1
                items.append(
                    RetryFailedImportRunItemDTO(
                        run_id=run.id,
                        project_id=run.project_id,
                        status="FAILED",
                        imported=0,
                        skipped=0,
                        errors_count=1,
                        last_error=str(e)[:300],
                    )
                )
                continue

            successful_runs += 1
            items.append(
                RetryFailedImportRunItemDTO(
                    run_id=run.id,
                    project_id=run.project_id,
                    status="SUCCESS",
                    imported=int(result.imported),
                    skipped=int(result.skipped),
                    errors_count=len(result.errors),
                    last_error=None,
                )
            )

        return RetryFailedImportRunsResponse(
            items=items,
            total_runs=len(unique_run_ids),
            successful_runs=successful_runs,
            failed_runs=failed_runs,
            skipped_runs=skipped_runs,
        )

    @staticmethod
    def bulk_reconcile_latest_imports(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        project_ids: list[uuid.UUID],
        only_failed_runs: bool = False,
    ) -> ProjectBulkImportReconcileResponse:
        items: list[ProjectBulkImportReconcileItemDTO] = []
        success_count = 0
        failed_count = 0
        skipped_count = 0

        for project_id in project_ids:
            project = uow.projects.get(company_id=company_id, project_id=project_id)
            if project is None:
                failed_count += 1
                items.append(
                    ProjectBulkImportReconcileItemDTO(
                        project_id=project_id,
                        source_run_id=None,
                        status="FAILED_PROJECT_NOT_FOUND",
                        imported=0,
                        skipped=0,
                        errors_count=1,
                        last_error="Project not found",
                    )
                )
                continue

            source_run = uow.project_import_runs.latest_retryable_for_project(
                company_id=company_id,
                project_id=project_id,
            )
            if source_run is None:
                skipped_count += 1
                items.append(
                    ProjectBulkImportReconcileItemDTO(
                        project_id=project_id,
                        source_run_id=None,
                        status="SKIPPED_NO_RUN",
                        imported=0,
                        skipped=0,
                        errors_count=0,
                        last_error=None,
                    )
                )
                continue

            source_payload = _public_payload(source_run.result_payload)
            source_errors_count = _errors_count_from_payload(source_payload)
            source_status = _import_run_status(
                mode=str(source_run.import_mode or ""),
                imported=_safe_int(source_payload.get("imported"), 0),
                errors_count=source_errors_count,
            )
            if only_failed_runs and source_status not in {"FAILED", "PARTIAL"}:
                skipped_count += 1
                items.append(
                    ProjectBulkImportReconcileItemDTO(
                        project_id=project_id,
                        source_run_id=source_run.id,
                        status="SKIPPED_NOT_FAILED",
                        imported=0,
                        skipped=0,
                        errors_count=0,
                        last_error=None,
                    )
                )
                continue

            try:
                result = _run_retry_import(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                    source_run=source_run,
                    audit_action="PROJECT_DOORS_IMPORT_RETRY_BULK",
                )
            except Exception as e:
                failed_count += 1
                items.append(
                    ProjectBulkImportReconcileItemDTO(
                        project_id=project_id,
                        source_run_id=source_run.id,
                        status="FAILED",
                        imported=0,
                        skipped=0,
                        errors_count=1,
                        last_error=str(e)[:300],
                    )
                )
                continue

            success_count += 1
            items.append(
                ProjectBulkImportReconcileItemDTO(
                    project_id=project_id,
                    source_run_id=source_run.id,
                    status="SUCCESS",
                    imported=int(result.imported),
                    skipped=int(result.skipped),
                    errors_count=len(result.errors),
                    last_error=None,
                )
            )

        return ProjectBulkImportReconcileResponse(
            items=items,
            total_projects=len(project_ids),
            successful_projects=success_count,
            failed_projects=failed_count,
            skipped_projects=skipped_count,
        )

    @staticmethod
    def create_project(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        name: str,
        address: str,
        developer_company: str | None,
        contact_name: str | None,
        contact_phone: str | None,
        contact_email: str | None,
    ) -> ProjectCreateResponse:
        try:
            p = ProjectUseCases.create_project(
                uow,
                company_id=company_id,
                name=name,
                address=address,
                developer_company=developer_company,
                contact_name=contact_name,
                contact_phone=contact_phone,
                contact_email=contact_email,
            )
        except CompanyPlanLimitExceeded as e:
            AuditService.add_independent(
                company_id=company_id,
                actor_user_id=actor_user_id,
                entity_type="company_plan",
                entity_id=company_id,
                action="PLAN_LIMIT_BLOCK_PROJECT_CREATE",
                before=e.details or None,
                after={"requested": "project_create"},
            )
            raise
        CompanyLimitAlertsService.evaluate_and_alert(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            metric_keys=["projects"],
        )
        return ProjectCreateResponse(id=p.id)

    @staticmethod
    def update_project(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        payload: dict,
    ) -> None:
        ProjectUseCases.update_project(
            uow,
            company_id=company_id,
            project_id=project_id,
            **payload,
        )

    @staticmethod
    def delete_project(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        ProjectUseCases.delete_project(
            uow,
            company_id=company_id,
            project_id=project_id,
        )

    @staticmethod
    def import_doors(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        project_id: uuid.UUID,
        rows: list[dict],
    ) -> ImportDoorsResponse:
        try:
            imported, _skipped = ProjectUseCases.import_doors(
                uow,
                company_id=company_id,
                project_id=project_id,
                rows=rows,
            )
        except CompanyPlanLimitExceeded as e:
            AuditService.add_independent(
                company_id=company_id,
                actor_user_id=actor_user_id,
                entity_type="company_plan",
                entity_id=company_id,
                action="PLAN_LIMIT_BLOCK_DOOR_IMPORT",
                before=e.details or None,
                after={
                    "requested": "doors_import",
                    "project_id": str(project_id),
                    "rows": len(rows),
                },
            )
            raise
        if imported > 0:
            CompanyLimitAlertsService.evaluate_and_alert(
                uow,
                company_id=company_id,
                actor_user_id=actor_user_id,
                metric_keys=["doors_per_project"],
            )
        return ImportDoorsResponse(imported=imported)

    @staticmethod
    def import_doors_from_file(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        project_id: uuid.UUID,
        filename: str,
        content_base64: str,
        default_door_type_id: uuid.UUID | None,
        default_our_price,
        delimiter: str | None,
        mapping_profile: str,
        strict_required_fields: bool | None,
        create_missing_door_types: bool,
        analyze_only: bool,
    ) -> ImportDoorsFromFileResponse:
        try:
            data = ProjectFileImportService.import_project_doors_from_file(
                uow,
                company_id=company_id,
                project_id=project_id,
                filename=filename,
                content_base64=content_base64,
                default_door_type_id=default_door_type_id,
                default_our_price=default_our_price,
                delimiter=delimiter,
                mapping_profile=mapping_profile,
                strict_required_fields=strict_required_fields,
                create_missing_door_types=create_missing_door_types,
                analyze_only=analyze_only,
            )
        except CompanyPlanLimitExceeded as e:
            AuditService.add_independent(
                company_id=company_id,
                actor_user_id=actor_user_id,
                entity_type="company_plan",
                entity_id=company_id,
                action="PLAN_LIMIT_BLOCK_DOOR_IMPORT",
                before=e.details or None,
                after={
                    "requested": "doors_import_file",
                    "project_id": str(project_id),
                    "filename": filename,
                },
            )
            raise
        mode = str(data.get("mode") or ("analyze" if analyze_only else "import"))
        action = (
            "PROJECT_DOORS_IMPORT_ANALYZE"
            if mode == "analyze"
            else "PROJECT_DOORS_IMPORT_APPLY"
        )
        AuditService.add_independent(
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="project",
            entity_id=project_id,
            action=action,
            after=_audit_import_after(filename=filename, data=data),
        )
        if int(data.get("imported", 0)) > 0:
            CompanyLimitAlertsService.evaluate_and_alert(
                uow,
                company_id=company_id,
                actor_user_id=actor_user_id,
                metric_keys=["doors_per_project"],
            )
        return ImportDoorsFromFileResponse(**data)

    @staticmethod
    def project_details(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        order_number: str | None = None,
    ) -> dict:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found", details={"project_id": str(project_id)}
            )

        doors = uow.doors.list_by_project(
            company_id=company_id, project_id=project_id
        )
        if order_number is not None:
            doors = [
                d
                for d in doors
                if _order_number_matches(getattr(d, "order_number", None), order_number)
            ]
        issues = uow.issues.list_open_by_project(
            company_id=company_id, project_id=project_id
        )
        if order_number is not None:
            allowed_door_ids = {d.id for d in doors}
            issues = [i for i in issues if i.door_id in allowed_door_ids]

        return {
            "id": project.id,
            "name": project.name,
            "address": project.address,
            "status": _status_value(project.status),
            "developer_company": project.developer_company,
            "contact_name": project.contact_name,
            "contact_phone": project.contact_phone,
            "contact_email": project.contact_email,
            "doors": [
                {
                    "id": d.id,
                    "unit_label": d.unit_label,
                    "door_type_id": d.door_type_id,
                    "our_price": d.our_price,
                    "order_number": getattr(d, "order_number", None),
                    "house_number": getattr(d, "house_number", None),
                    "floor_label": getattr(d, "floor_label", None),
                    "apartment_number": getattr(d, "apartment_number", None),
                    "location_code": getattr(d, "location_code", None),
                    "door_marking": getattr(d, "door_marking", None),
                    "status": _status_value(d.status),
                    "installer_id": d.installer_id,
                    "reason_id": d.reason_id,
                    "comment": d.comment,
                    "is_locked": d.is_locked,
                }
                for d in doors
            ],
            "issues_open": [
                {
                    "id": i.id,
                    "door_id": i.door_id,
                    "status": _status_value(i.status),
                    "title": i.title,
                    "details": i.details,
                }
                for i in issues
            ],
        }

    @staticmethod
    def project_doors_layout(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        order_number: str | None = None,
    ) -> dict:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found", details={"project_id": str(project_id)}
            )

        buckets: dict[tuple[str, str, str, str, str], dict] = {}
        doors = uow.doors.list_by_project(
            company_id=company_id,
            project_id=project_id,
        )
        if order_number is not None:
            doors = [
                d
                for d in doors
                if _order_number_matches(getattr(d, "order_number", None), order_number)
            ]
        for d in doors:
            order_number = _empty_to_none(getattr(d, "order_number", None))
            house_number = _empty_to_none(getattr(d, "house_number", None))
            floor_label = _empty_to_none(getattr(d, "floor_label", None))
            location_code = _empty_to_none(getattr(d, "location_code", None))
            door_marking = _empty_to_none(getattr(d, "door_marking", None))
            key = (
                order_number or "",
                house_number or "",
                floor_label or "",
                location_code or "",
                door_marking or "",
            )
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {
                    "order_number": order_number,
                    "house_number": house_number,
                    "floor_label": floor_label,
                    "location_code": location_code,
                    "door_marking": door_marking,
                    "total": 0,
                    "status_breakdown": {},
                    "doors": [],
                }
                buckets[key] = bucket

            status_value = _status_value(d.status)
            bucket["total"] += 1
            bucket["status_breakdown"][status_value] = (
                bucket["status_breakdown"].get(status_value, 0) + 1
            )
            bucket["doors"].append(
                {
                    "id": d.id,
                    "unit_label": d.unit_label,
                    "door_type_id": d.door_type_id,
                    "order_number": order_number,
                    "apartment_number": _empty_to_none(
                        getattr(d, "apartment_number", None)
                    ),
                    "location_code": location_code,
                    "door_marking": door_marking,
                    "status": status_value,
                    "installer_id": d.installer_id,
                }
            )

        sorted_buckets = sorted(
            buckets.values(),
            key=lambda b: (
                (b["order_number"] or "").casefold(),
                (b["house_number"] or "").casefold(),
                _floor_sort_key(b["floor_label"]),
                (b["location_code"] or "").casefold(),
                (b["door_marking"] or "").casefold(),
            ),
        )
        for bucket in sorted_buckets:
            bucket["doors"].sort(
                key=lambda x: (
                    (x["apartment_number"] or "").casefold(),
                    x["unit_label"].casefold(),
                )
            )

        return {
            "project_id": project_id,
            "total_doors": len(doors),
            "buckets": sorted_buckets,
        }

    @staticmethod
    def assign_installer_to_door(
        uow,
        *,
        company_id: uuid.UUID,
        door_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> None:
        ProjectUseCases.assign_installer_to_door(
            uow,
            company_id=company_id,
            door_id=door_id,
            installer_id=installer_id,
        )
