from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.modules.addons.application.use_cases import AddonsUseCases
from app.modules.addons.domain.enums import AddonFactSource
from app.modules.doors.application.commands import (
    MarkDoorInstalled,
    MarkDoorNotInstalled,
)
from app.modules.doors.application.use_cases import DoorUseCases
from app.modules.sync.domain.enums import SyncEventType
from app.shared.application.navigation import build_waze_url
from app.shared.domain.errors import Forbidden, NotFound, ValidationError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InstallerSyncService:
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
                "change_type": str(r.change_type),
                "payload": r.payload,
            }
            for r in rows
        ]
        next_cursor = rows[-1].cursor_id if rows else since_cursor

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
                if uow.sync_events.exists_client_event(
                    company_id=company_id, client_event_id=cid
                ):
                    acks.append(
                        {
                            "client_event_id": cid,
                            "ok": True,
                            "applied": False,
                            "error": None,
                        }
                    )
                    continue

                etype = SyncEventType(ev["type"])
                project_id = ev["project_id"]
                happened_at = ev.get("happened_at")
                payload = ev.get("payload") or {}

                row = uow.sync_events.create_pending(
                    company_id=company_id,
                    installer_id=installer_id,
                    project_id=project_id,
                    event_type=etype,
                    client_event_id=cid,
                    client_happened_at=happened_at,
                    payload=payload,
                )

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
                try:
                    if row is not None and getattr(row, "client_event_id", None) == cid:
                        uow.sync_events.mark_failed(row, error=str(e))
                except Exception:
                    pass

                acks.append(
                    {
                        "client_event_id": cid,
                        "ok": False,
                        "applied": False,
                        "error": str(e),
                    }
                )

        return acks

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

        if getattr(d, "installer_id", None) is not None and d.installer_id != installer_id:
            raise Forbidden("Door is assigned to another installer")

        if str(getattr(d, "status", "")) == "INSTALLED":
            raise Forbidden("Door is locked (already INSTALLED)")

        if status == "INSTALLED":
            DoorUseCases.mark_installed(
                uow,
                MarkDoorInstalled(
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    door_id=d.id,
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
                ),
            )
        else:
            raise ValidationError(
                "payload status must be INSTALLED or NOT_INSTALLED"
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
        projects = [
            {
                "id": str(p.id),
                "name": p.name,
                "address": getattr(p, "address", None),
                "status": p.status.value if hasattr(p.status, "value") else str(p.status),
                "waze_url": build_waze_url(address=getattr(p, "address", None)),
            }
            for p in uow.projects.list_by_ids(
                company_id=company_id,
                ids=[uuid.UUID(pid) for pid in project_ids],
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
        for pid in project_ids:
            pid_uuid = uuid.UUID(pid)
            rows = uow.addon_plans.list_by_project(
                company_id=company_id, project_id=pid_uuid
            )
            plans.extend(
                [
                    {
                        "project_id": str(pid),
                        "addon_type_id": str(r.addon_type_id),
                        "qty_planned": str(r.qty_planned),
                        "client_price": str(r.client_price),
                        "installer_price": str(r.installer_price),
                    }
                    for r in rows
                ]
            )

        addon_facts = InstallerSyncService._pull_addon_facts(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            since=None,
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

        return {
            "projects": projects,
            "doors": doors,
            "door_types": door_types,
            "reasons": reasons,
            "addon_types": addon_types,
            "addon_plans": plans,
            "addon_facts": addon_facts,
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
    ) -> list[dict]:
        from app.modules.addons.infrastructure.models import ProjectAddonFactORM

        q = uow.session.query(ProjectAddonFactORM).filter(
            ProjectAddonFactORM.company_id == company_id,
            ProjectAddonFactORM.installer_id == installer_id,
        )
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
                "updated_at": r.updated_at,
            }
            for r in rows
        ]
