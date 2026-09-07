from __future__ import annotations

from datetime import datetime, timezone

from app.modules.doors.application.completion import enum_value


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_door_sync_payload(door) -> dict:
    return {
        "id": str(door.id),
        "project_id": str(door.project_id),
        "door_type_id": str(door.door_type_id),
        "unit_label": door.unit_label,
        "order_number": door.order_number,
        "house_number": door.house_number,
        "floor_label": door.floor_label,
        "apartment_number": door.apartment_number,
        "location_code": door.location_code,
        "door_marking": door.door_marking,
        "status": enum_value(door.status),
        "reason_id": str(door.reason_id) if door.reason_id else None,
        "comment": door.comment,
        "is_locked": bool(door.is_locked),
        "updated_at": door.updated_at.isoformat() if door.updated_at else utcnow_iso(),
        "version": int(getattr(door, "version", 0) or 0),
    }
