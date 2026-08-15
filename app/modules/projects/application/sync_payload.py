from __future__ import annotations

from datetime import datetime, timezone

from app.modules.doors.application.completion import enum_value
from app.shared.application.navigation import build_waze_url


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_project_sync_payload(project) -> dict:
    address = getattr(project, "address", None)
    explicit_waze_url = getattr(project, "address_waze_url", None)
    updated_at = getattr(project, "updated_at", None)

    return {
        "id": str(project.id),
        "name": project.name,
        "address": address,
        "status": enum_value(project.status),
        "lifecycle_status": enum_value(project.lifecycle_status),
        "health_status": enum_value(project.health_status),
        "waze_url": explicit_waze_url or build_waze_url(address=address),
        "updated_at": updated_at.isoformat() if updated_at else utcnow_iso(),
    }
