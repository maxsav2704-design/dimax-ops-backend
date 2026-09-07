from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.modules.addons.application.use_cases import AddonsUseCases
from app.modules.addons.domain.enums import AddonFactSource
from app.modules.doors.application.completion import enum_value
from app.modules.doors.application.installer_service import InstallerDoorService
from app.modules.doors.application.commands import MarkDoorInstalled, MarkDoorNotInstalled
from app.modules.doors.application.use_cases import DoorUseCases
from app.modules.doors.domain.enums import DoorStatus
from app.modules.issues.application.installer_api_service import InstallerIssuesApiService
from app.modules.projects.application.sync_payload import build_project_sync_payload
from app.modules.sync.domain.enums import SyncChangeType, SyncEventType
from app.shared.domain.errors import (
    Conflict,
    Forbidden,
    NotFound,
    Unauthorized,
    ValidationError,
)
from app.shared.infrastructure.observability import get_logger, log_event


logger = get_logger(__name__)


class _SyncConflictError(Exception):
    def __init__(self, conflict_code: str, message: str):
        super().__init__(message)
        self.conflict_code = conflict_code
        self.message = message


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InstallerSyncService:
    @staticmethod
    def _domain_error_to_conflict(exc: Exception) -> _SyncConflictError:
        message = str(exc)
        lowered = message.lower()
        if (
            "assigned" in lowered
            or "not available" in lowered
            or "not found in project" in lowered
        ):
            return _SyncConflictError(
                "CONFLICT_ASSIGNMENT_CHANGED",
                message,
            )
        return _SyncConflictError(
            "CONFLICT_INVALID_TRANSITION",
            message,
        )

    @staticmethod
    def _sync_event_error_code(exc: Exception) -> str:
        if isinstance(exc, Unauthorized):
            return "AUTH_REQUIRED"
        if isinstance(exc, _SyncConflictError):
            return exc.conflict_code
        if isinstance(exc, (ValidationError, Forbidden, NotFound, Conflict)):
            return InstallerSyncService._domain_error_to_conflict(exc).conflict_code
        return str(exc)

    @staticmethod
    def _existing_event_ack(
        existing_event,
        *,
        installer_id: uuid.UUID,
        client_event_id: str,
    ) -> dict:
        if existing_event.installer_id != installer_id:
            return {
                "client_event_id": client_event_id,
                "ok": False,
                "applied": False,
                "error": "CONFLICT_ASSIGNMENT_CHANGED",
            }
        if existing_event.apply_error:
            return {
                "client_event_id": client_event_id,
                "ok": False,
                "applied": False,
                "error": existing_event.apply_error,
            }
        return {
            "client_event_id": client_event_id,
            "ok": True,
            "applied": False,
            "error": None,
        }

    @staticmethod
    def _only(payload: dict, allowed_keys: set[str]) -> dict:
        return {key: payload[key] for key in allowed_keys if key in payload}

    @staticmethod
    def _sanitize_installer_change_payload(change_type, payload: dict | None) -> dict:
        payload = payload or {}
        change_type_value = enum_value(change_type)

        if change_type_value == SyncChangeType.DOOR.value:
            return InstallerSyncService._only(
                payload,
                {
                    "id",
                    "project_id",
                    "door_type_id",
                    "unit_label",
                    "order_number",
                    "house_number",
                    "floor_label",
                    "apartment_number",
                    "location_code",
                    "door_marking",
                    "status",
                    "reason_id",
                    "comment",
                    "is_locked",
                    "updated_at",
                    "version",
                },
            )

        if change_type_value == SyncChangeType.ADDON_FACT.value:
            return InstallerSyncService._only(
                payload,
                {
                    "id",
                    "project_id",
                    "addon_type_id",
                    "installer_id",
                    "qty_done",
                    "done_at",
                    "comment",
                    "source",
                    "updated_at",
                },
            )

        if change_type_value == SyncChangeType.PROJECT_ADDON_PLAN.value:
            sanitized = InstallerSyncService._only(
                payload,
                {
                    "kind",
                    "project_id",
                    "deleted_addon_type_id",
                    "plan_items",
                },
            )
            if isinstance(sanitized.get("plan_items"), list):
                sanitized["plan_items"] = [
                    InstallerSyncService._only(
                        item,
                        {"addon_type_id", "qty_planned"},
                    )
                    for item in sanitized["plan_items"]
                    if isinstance(item, dict)
                ]
            return sanitized

        if change_type_value == SyncChangeType.PROJECT_ASSIGNMENTS.value:
            return InstallerSyncService._only(
                payload,
                {"kind", "project_id", "affected_door_ids"},
            )

        if change_type_value == SyncChangeType.PROJECT_BASE.value:
            return InstallerSyncService._only(
                payload,
                {
                    "id",
                    "name",
                    "address",
                    "status",
                    "waze_url",
                    "updated_at",
                },
            )

        if change_type_value == SyncChangeType.CATALOG_ADDON_TYPES.value:
            sanitized = InstallerSyncService._only(payload, {"items"})
            if isinstance(sanitized.get("items"), list):
                sanitized["items"] = [
                    InstallerSyncService._only(item, {"id", "name", "unit"})
                    for item in sanitized["items"]
                    if isinstance(item, dict)
                ]
            return sanitized

        return {}

    @staticmethod
    def sync_batch(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        app_version: str | None,
        device_id: str,
        items: list[dict],
    ) -> dict:
        log_event(
            logger,
            "installer.sync_batch.requested",
            company_id=company_id,
            installer_id=installer_id,
            actor_user_id=actor_user_id,
            items_count=len(items),
            app_version=app_version,
            device_id=device_id,
        )
        uow.sync_state.ack_cursor(
            company_id=company_id,
            installer_id=installer_id,
            cursor=0,
            app_version=app_version,
            device_id=device_id,
        )

        results: list[dict] = []
        for item in items:
            existing = uow.sync_queue.get(
                company_id=company_id,
                item_id=uuid.UUID(str(item["id"])),
                user_id=actor_user_id,
            )
            if existing is not None and existing.status == "APPLIED":
                results.append(
                    InstallerSyncService._applied_batch_result(
                        uow,
                        company_id=company_id,
                        row=existing,
                    )
                )
                continue

            row = uow.sync_queue.create_or_update_pending(
                company_id=company_id,
                user_id=actor_user_id,
                item_id=uuid.UUID(str(item["id"])),
                device_id=device_id,
                project_id=uuid.UUID(str(item["project_id"])),
                entity_type=item["entity_type"],
                entity_id=uuid.UUID(str(item["entity_id"])),
                operation_type=item["operation_type"],
                payload=item.get("payload") or {},
                base_version=int(item.get("base_version") or 0),
            )
            try:
                with uow.session.begin_nested():
                    result = InstallerSyncService._apply_batch_item(
                        uow,
                        company_id=company_id,
                        installer_id=installer_id,
                        actor_user_id=actor_user_id,
                        item=item,
                    )
                uow.sync_queue.mark_applied(row)
                results.append(
                    {
                        "item_id": row.id,
                        "status": "APPLIED",
                        "new_version": result.get("new_version"),
                        "conflict_code": None,
                        "message": None,
                    }
                )
            except Unauthorized as exc:
                uow.sync_queue.mark_auth_required(row)
                results.append(
                    {
                        "item_id": row.id,
                        "status": "AUTH_REQUIRED",
                        "new_version": None,
                        "conflict_code": None,
                        "message": exc.message,
                    }
                )
            except (ValidationError, Forbidden, NotFound, Conflict) as exc:
                mapped = InstallerSyncService._domain_error_to_conflict(exc)
                uow.sync_queue.mark_conflict(
                    row,
                    conflict_code=mapped.conflict_code,
                )
                results.append(
                    {
                        "item_id": row.id,
                        "status": "CONFLICT",
                        "new_version": None,
                        "conflict_code": mapped.conflict_code,
                        "message": mapped.message,
                    }
                )
            except _SyncConflictError as exc:
                uow.sync_queue.mark_conflict(
                    row,
                    conflict_code=exc.conflict_code,
                )
                results.append(
                    {
                        "item_id": row.id,
                        "status": "CONFLICT",
                        "new_version": None,
                        "conflict_code": exc.conflict_code,
                        "message": exc.message,
                    }
                )

        return {
            "server_time": utcnow(),
            "results": results,
        }

    @staticmethod
    def _applied_batch_result(
        uow,
        *,
        company_id: uuid.UUID,
        row,
    ) -> dict:
        new_version = None
        if row.operation_type == "DOOR_SET_STATUS":
            door = uow.doors.get(company_id=company_id, door_id=row.entity_id)
            if door is not None:
                new_version = int(getattr(door, "version", 0) or 0)

        return {
            "item_id": row.id,
            "status": "APPLIED",
            "new_version": new_version,
            "conflict_code": None,
            "message": None,
        }

    @staticmethod
    def sync_v2(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        since_cursor: int,
        ack_cursor: int,
        app_version: str | None,
        device_id: str | None,
        events: list[dict],
    ) -> dict:
        log_event(
            logger,
            "installer.sync.requested",
            company_id=company_id,
            installer_id=installer_id,
            actor_user_id=actor_user_id,
            since_cursor=since_cursor,
            ack_cursor=ack_cursor,
            events_count=len(events),
            app_version=app_version,
            device_id=device_id,
        )
        max_acknowledgeable = uow.sync_change_log.max_cursor(company_id=company_id)
        if ack_cursor > max_acknowledgeable:
            raise ValidationError(
                "ack_cursor cannot be ahead of the server cursor",
                field="ack_cursor",
                meta={
                    "ack_cursor": ack_cursor,
                    "max_cursor": max_acknowledgeable,
                },
            )
        uow.sync_state.ack_cursor(
            company_id=company_id,
            installer_id=installer_id,
            cursor=int(ack_cursor or 0),
            app_version=app_version,
            device_id=device_id,
        )

        acks = InstallerSyncService._apply_events(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            actor_user_id=actor_user_id,
            events=events,
        )

        uow.session.flush()

        min_available = uow.sync_change_log.min_cursor(company_id=company_id)
        max_now = uow.sync_change_log.max_cursor(company_id=company_id)

        if min_available is not None and since_cursor < min_available:
            snapshot = InstallerSyncService._build_cold_snapshot(
                uow,
                company_id=company_id,
                installer_id=installer_id,
            )
            ack_ok = sum(1 for item in acks if item.get("ok"))
            ack_failed = sum(1 for item in acks if not item.get("ok"))
            ack_duplicates = sum(1 for item in acks if not item.get("applied") and item.get("ok"))
            log_event(
                logger,
                "installer.sync.completed",
                company_id=company_id,
                installer_id=installer_id,
                next_cursor=max_now,
                reset_required=True,
                ack_ok=ack_ok,
                ack_failed=ack_failed,
                ack_duplicates=ack_duplicates,
                changes_count=0,
                snapshot_projects=len(snapshot.get("projects") or []),
                snapshot_doors=len(snapshot.get("doors") or []),
            )
            return {
                "server_time": utcnow(),
                "next_cursor": max_now,
                "reset_required": True,
                "snapshot": snapshot,
                "acks": acks,
                "changes": [],
            }

        limit = 2000
        rows = uow.sync_change_log.pull_for_installer(
            company_id=company_id,
            installer_id=installer_id,
            since_cursor=since_cursor,
            limit=limit,
        )

        changes = [
            {
                "cursor_id": r.cursor_id,
                "change_type": enum_value(r.change_type),
                "payload": InstallerSyncService._sanitize_installer_change_payload(
                    r.change_type,
                    r.payload,
                ),
            }
            for r in rows
        ]
        next_cursor = rows[-1].cursor_id if rows else since_cursor

        ack_ok = sum(1 for item in acks if item.get("ok"))
        ack_failed = sum(1 for item in acks if not item.get("ok"))
        ack_duplicates = sum(1 for item in acks if not item.get("applied") and item.get("ok"))
        log_event(
            logger,
            "installer.sync.completed",
            company_id=company_id,
            installer_id=installer_id,
            next_cursor=next_cursor,
            reset_required=False,
            ack_ok=ack_ok,
            ack_failed=ack_failed,
            ack_duplicates=ack_duplicates,
            changes_count=len(changes),
        )

        return {
            "server_time": utcnow(),
            "next_cursor": next_cursor,
            "acks": acks,
            "changes": changes,
        }

    @staticmethod
    def _apply_events(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        events: list[dict],
    ) -> list[dict]:
        acks: list[dict] = []

        for ev in events:
            cid = ev["client_event_id"]
            row = None
            try:
                existing_event = uow.sync_events.get_by_client_event(
                    company_id=company_id, client_event_id=cid
                )
                if existing_event is not None:
                    acks.append(
                        InstallerSyncService._existing_event_ack(
                            existing_event,
                            installer_id=installer_id,
                            client_event_id=cid,
                        )
                    )
                    continue

                etype = SyncEventType(ev["type"])
                project_id = ev["project_id"]
                happened_at = ev.get("happened_at")
                payload = ev.get("payload") or {}

                try:
                    with uow.session.begin_nested():
                        row = uow.sync_events.create_pending(
                            company_id=company_id,
                            installer_id=installer_id,
                            project_id=project_id,
                            event_type=etype,
                            client_event_id=cid,
                            client_happened_at=happened_at,
                            payload=payload,
                        )
                        uow.session.flush([row])
                except IntegrityError:
                    existing_event = uow.sync_events.get_by_client_event(
                        company_id=company_id,
                        client_event_id=cid,
                    )
                    if existing_event is None:
                        raise
                    acks.append(
                        InstallerSyncService._existing_event_ack(
                            existing_event,
                            installer_id=installer_id,
                            client_event_id=cid,
                        )
                    )
                    continue

                with uow.session.begin_nested():
                    if etype == SyncEventType.DOOR_SET_STATUS:
                        InstallerSyncService._apply_door_set_status(
                            uow,
                            company_id=company_id,
                            installer_id=installer_id,
                            actor_user_id=actor_user_id,
                            project_id=project_id,
                            payload=payload,
                        )
                    elif etype == SyncEventType.ADDON_FACT_CREATE:
                        InstallerSyncService._apply_addon_fact_create(
                            uow,
                            company_id=company_id,
                            installer_id=installer_id,
                            project_id=project_id,
                            payload=payload,
                            client_event_id=cid,
                            happened_at=happened_at,
                        )
                    elif etype == SyncEventType.ISSUE_CREATE:
                        InstallerSyncService._apply_issue_create(
                            uow,
                            company_id=company_id,
                            installer_id=installer_id,
                            actor_user_id=actor_user_id,
                            project_id=project_id,
                            payload=payload,
                        )
                    else:
                        raise ValidationError(
                            f"Unsupported sync event type: {etype}"
                        )

                    uow.sync_events.mark_applied(row)
                acks.append(
                    {
                        "client_event_id": cid,
                        "ok": True,
                        "applied": True,
                        "error": None,
                    }
                )

            except Exception as e:
                error_code = InstallerSyncService._sync_event_error_code(e)
                log_event(
                    logger,
                    "installer.sync.event_failed",
                    level="warning",
                    company_id=company_id,
                    installer_id=installer_id,
                    actor_user_id=actor_user_id,
                    client_event_id=cid,
                    event_type=ev.get("type"),
                    project_id=ev.get("project_id"),
                    error=str(e),
                    error_code=error_code,
                )
                try:
                    if row is not None and getattr(row, "client_event_id", None) == cid:
                        uow.sync_events.mark_failed(row, error=error_code)
                except Exception:
                    pass

                acks.append(
                    {
                        "client_event_id": cid,
                        "ok": False,
                        "applied": False,
                        "error": error_code,
                    }
                )

        return acks

    @staticmethod
    def _apply_batch_item(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        item: dict,
    ) -> dict:
        operation_type = item["operation_type"]
        project_id = uuid.UUID(str(item["project_id"]))
        payload = item.get("payload") or {}
        base_version = int(item.get("base_version") or 0)
        happened_at = item.get("happened_at")

        if operation_type == "DOOR_SET_STATUS":
            return InstallerSyncService._apply_batch_door_set_status(
                uow,
                company_id=company_id,
                installer_id=installer_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
                payload=payload,
                base_version=base_version,
            )

        if operation_type == "ADDON_FACT_CREATE":
            InstallerSyncService._apply_addon_fact_create(
                uow,
                company_id=company_id,
                installer_id=installer_id,
                project_id=project_id,
                payload=payload,
                client_event_id=str(item["id"]),
                happened_at=happened_at,
            )
            return {"new_version": None}

        raise ValidationError(f"Unsupported sync operation type: {operation_type}")

    @staticmethod
    def _ensure_project_access(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        my_doors = uow.doors.list_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )
        if not my_doors:
            raise Forbidden("Project is not assigned to this installer")

    @staticmethod
    def _apply_issue_create(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        project_id: uuid.UUID,
        payload: dict,
    ) -> None:
        door_id = payload.get("door_id")
        if not door_id:
            raise ValidationError("payload requires door_id")

        door = uow.doors.get(
            company_id=company_id,
            door_id=uuid.UUID(str(door_id)),
        )
        if door is None or door.project_id != project_id:
            raise NotFound("Door not found in project")
        if getattr(door, "installer_id", None) != installer_id:
            raise Forbidden("Door is not assigned to this installer")

        title = str(payload.get("title") or "").strip() or None
        details = str(payload.get("details") or "").strip() or None
        if title is not None and len(title) > 200:
            raise ValidationError("issue title must be at most 200 characters")
        if details is not None and len(details) > 2000:
            raise ValidationError("issue details must be at most 2000 characters")
        if title is None and details is None:
            raise ValidationError("issue title or details is required")

        InstallerIssuesApiService.create_issue(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            created_by_user_id=actor_user_id,
            door_id=door.id,
            title=title,
            details=details,
            source="OFFLINE_SYNC",
        )

    @staticmethod
    def _apply_door_set_status(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        project_id: uuid.UUID,
        payload: dict,
    ) -> None:
        InstallerSyncService._ensure_project_access(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            project_id=project_id,
        )

        door_id = payload.get("door_id")
        status = payload.get("status")
        reason_id = payload.get("reason_id")
        comment = payload.get("comment")

        if not door_id or not status:
            raise ValidationError("payload requires door_id and status")

        d = uow.doors.get(
            company_id=company_id, door_id=uuid.UUID(str(door_id))
        )
        if not d or d.project_id != project_id:
            raise NotFound("Door not found in project")

        if getattr(d, "installer_id", None) != installer_id:
            raise Forbidden("Door is not assigned to this installer")

        payload_version = payload.get("base_version")
        if payload_version is None:
            payload_version = payload.get("previous_version")
        if payload_version is not None:
            try:
                expected_version = int(payload_version)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    "payload previous_version must be an integer"
                ) from exc
            current_version = int(getattr(d, "version", 0) or 0)
            if current_version != expected_version:
                raise Conflict(
                    "Door changed since this offline action was queued"
                )

        if enum_value(getattr(d, "status", "")) == "INSTALLED":
            raise Forbidden("Door is locked (already INSTALLED)")

        if status == "INSTALLED":
            DoorUseCases.mark_installed(
                uow,
                MarkDoorInstalled(
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    door_id=d.id,
                    source="OFFLINE_SYNC",
                ),
            )
        elif status == "NOT_INSTALLED":
            if not reason_id:
                raise ValidationError(
                    "payload requires reason_id for NOT_INSTALLED"
                )
            DoorUseCases.mark_not_installed(
                uow,
                MarkDoorNotInstalled(
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    door_id=d.id,
                    reason_id=uuid.UUID(str(reason_id)),
                    comment=comment,
                    source="OFFLINE_SYNC",
                ),
            )
        else:
            raise ValidationError(
                "payload status must be INSTALLED or NOT_INSTALLED"
            )

    @staticmethod
    def _apply_batch_door_set_status(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        project_id: uuid.UUID,
        payload: dict,
        base_version: int,
    ) -> dict:
        door_id = payload.get("door_id")
        status = str(payload.get("status") or "").strip().upper()
        reason_id = payload.get("reason_id")
        comment = payload.get("comment")

        if not door_id or not status:
            raise ValidationError("payload requires door_id and status")

        door = uow.doors.get(company_id=company_id, door_id=uuid.UUID(str(door_id)))
        if not door or door.project_id != project_id:
            raise _SyncConflictError(
                "CONFLICT_ASSIGNMENT_CHANGED",
                "Door assignment changed or door is no longer available",
            )

        if getattr(door, "installer_id", None) != installer_id:
            raise _SyncConflictError(
                "CONFLICT_ASSIGNMENT_CHANGED",
                "Door assignment changed or door is no longer available",
            )

        current_version = int(getattr(door, "version", 0) or 0)
        if current_version != base_version:
            raise _SyncConflictError(
                "CONFLICT_INVALID_TRANSITION",
                f"Stale base_version: expected {current_version}, got {base_version}",
            )

        if status == DoorStatus.IN_PROGRESS.value:
            try:
                result = InstallerDoorService.change_status(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    installer_id=installer_id,
                    door_id=door.id,
                    to_status=DoorStatus.IN_PROGRESS,
                    source="OFFLINE_SYNC",
                )
            except (ValidationError, Forbidden, Conflict) as exc:
                raise _SyncConflictError(
                    "CONFLICT_INVALID_TRANSITION",
                    str(exc),
                ) from exc
            return {"new_version": result["version"]}

        if status == DoorStatus.INSTALLED.value:
            try:
                result = InstallerDoorService.change_status(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    installer_id=installer_id,
                    door_id=door.id,
                    to_status=DoorStatus.INSTALLED,
                    source="OFFLINE_SYNC",
                )
            except (ValidationError, Forbidden, Conflict) as exc:
                raise _SyncConflictError(
                    "CONFLICT_INVALID_TRANSITION",
                    str(exc),
                ) from exc
            return {"new_version": result["version"]}

        if status == DoorStatus.NOT_INSTALLED.value:
            if not reason_id:
                raise _SyncConflictError(
                    "CONFLICT_INVALID_TRANSITION",
                    "payload requires reason_id for NOT_INSTALLED",
                )
            try:
                DoorUseCases.mark_not_installed(
                    uow,
                    MarkDoorNotInstalled(
                        company_id=company_id,
                        actor_user_id=actor_user_id,
                        door_id=door.id,
                        reason_id=uuid.UUID(str(reason_id)),
                        comment=comment,
                        source="OFFLINE_SYNC",
                    ),
                )
            except (ValidationError, Forbidden, Conflict, NotFound) as exc:
                raise _SyncConflictError(
                    "CONFLICT_INVALID_TRANSITION",
                    str(exc),
                ) from exc
            door = uow.doors.get(company_id=company_id, door_id=door.id)
            return {"new_version": int(getattr(door, "version", 0) or 0)}

        raise _SyncConflictError(
            "CONFLICT_INVALID_TRANSITION",
            "payload status must be IN_PROGRESS, INSTALLED or NOT_INSTALLED",
        )

    @staticmethod
    def _apply_addon_fact_create(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        project_id: uuid.UUID,
        payload: dict,
        client_event_id: str,
        happened_at: datetime | None,
    ) -> None:
        InstallerSyncService._ensure_project_access(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            project_id=project_id,
        )

        addon_type_id = payload.get("addon_type_id")
        qty_done = payload.get("qty_done")
        comment = payload.get("comment")

        if not addon_type_id or qty_done is None:
            raise ValidationError(
                "payload requires addon_type_id and qty_done"
            )

        result = AddonsUseCases.installer_add_fact(
            uow,
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
            addon_type_id=uuid.UUID(str(addon_type_id)),
            qty_done=Decimal(str(qty_done)),
            comment=comment,
            done_at=happened_at,
            source=AddonFactSource.OFFLINE,
            client_event_id=client_event_id,
        )
        if result is None:
            pass

    @staticmethod
    def _build_cold_snapshot(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> dict:
        doors = uow.doors.list_all_for_installer(
            company_id=company_id,
            installer_id=installer_id,
        )
        project_ids = sorted({d["project_id"] for d in doors})
        project_uuid_ids = [uuid.UUID(pid) for pid in project_ids]
        projects = [
            build_project_sync_payload(p)
            for p in uow.projects.list_by_ids(
                company_id=company_id,
                ids=project_uuid_ids,
            )
        ]
        door_types = [
            {"id": str(t.id), "code": t.code, "name": t.name}
            for t in uow.door_types.list_active(company_id=company_id)
        ]
        reasons = [
            {"id": str(r.id), "code": r.code, "name": r.name}
            for r in uow.reasons.list_active(company_id=company_id)
        ]

        addon_types = [
            {"id": str(t.id), "name": t.name, "unit": t.unit}
            for t in uow.addon_types.list_active(company_id=company_id)
        ]

        plans = []
        for pid_uuid in project_uuid_ids:
            rows = uow.addon_plans.list_by_project(
                company_id=company_id, project_id=pid_uuid
            )
            plans.extend(
                [
                    {
                        "project_id": str(pid_uuid),
                        "addon_type_id": str(r.addon_type_id),
                        "qty_planned": str(r.qty_planned),
                    }
                    for r in rows
                ]
            )

        addon_facts = InstallerSyncService._pull_addon_facts(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            since=None,
            project_ids=project_uuid_ids,
        )
        for f in addon_facts:
            if hasattr(f.get("id"), "__str__"):
                f["id"] = str(f["id"])
            if hasattr(f.get("project_id"), "__str__"):
                f["project_id"] = str(f["project_id"])
            if hasattr(f.get("addon_type_id"), "__str__"):
                f["addon_type_id"] = str(f["addon_type_id"])
            if hasattr(f.get("installer_id"), "__str__"):
                f["installer_id"] = str(f["installer_id"])
            if hasattr(f.get("done_at"), "isoformat"):
                f["done_at"] = f["done_at"].isoformat()
            if f.get("updated_at") and hasattr(f["updated_at"], "isoformat"):
                f["updated_at"] = f["updated_at"].isoformat()

        issues = []
        for pid_uuid in project_uuid_ids:
            rows = uow.issues.list_open_by_project_for_installer(
                company_id=company_id,
                project_id=pid_uuid,
                installer_id=installer_id,
            )
            issues.extend(
                [
                    {
                        "id": str(issue.id),
                        "door_id": str(issue.door_id),
                        "project_id": str(pid_uuid),
                        "status": enum_value(issue.status),
                        "title": issue.title,
                        "details": issue.details,
                    }
                    for issue in rows
                ]
            )

        return {
            "projects": projects,
            "doors": doors,
            "door_types": door_types,
            "reasons": reasons,
            "addon_types": addon_types,
            "addon_plans": plans,
            "addon_facts": addon_facts,
            "issues": issues,
        }

    @staticmethod
    def _pull_doors(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        since: datetime | None,
    ) -> list[dict]:
        return uow.doors.list_changes_for_installer(
            company_id=company_id,
            installer_id=installer_id,
            since=since,
        )

    @staticmethod
    def _pull_addon_facts(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        since: datetime | None,
        project_ids: list[uuid.UUID] | None = None,
    ) -> list[dict]:
        from app.modules.addons.infrastructure.models import ProjectAddonFactORM

        if project_ids is not None and not project_ids:
            return []

        q = uow.session.query(ProjectAddonFactORM).filter(
            ProjectAddonFactORM.company_id == company_id,
            ProjectAddonFactORM.installer_id == installer_id,
        )
        if project_ids is not None:
            q = q.filter(ProjectAddonFactORM.project_id.in_(project_ids))
        if since is not None:
            q = q.filter(ProjectAddonFactORM.updated_at > since)

        rows = (
            q.order_by(ProjectAddonFactORM.updated_at.asc())
            .limit(2000)
            .all()
        )
        return [
            {
                "id": r.id,
                "project_id": r.project_id,
                "addon_type_id": r.addon_type_id,
                "installer_id": r.installer_id,
                "qty_done": str(r.qty_done),
                "done_at": r.done_at,
                "comment": r.comment,
                "source": enum_value(r.source),
                "updated_at": r.updated_at,
            }
            for r in rows
        ]
