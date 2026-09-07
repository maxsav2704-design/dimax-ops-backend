from __future__ import annotations

from datetime import datetime, timezone


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


class InstallerDoorSerializer:
    ALLOWED_FIELDS = {
        "id",
        "unit_label",
        "door_type_id",
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
        "version",
    }

    @classmethod
    def serialize(cls, door) -> dict:
        payload = {
            "id": door.id,
            "unit_label": door.unit_label,
            "door_type_id": door.door_type_id,
            "order_number": getattr(door, "order_number", None),
            "house_number": getattr(door, "house_number", None),
            "floor_label": getattr(door, "floor_label", None),
            "apartment_number": getattr(door, "apartment_number", None),
            "location_code": getattr(door, "location_code", None),
            "door_marking": getattr(door, "door_marking", None),
            "status": _enum_value(door.status),
            "reason_id": door.reason_id,
            "comment": door.comment,
            "is_locked": door.is_locked,
            "version": int(getattr(door, "version", 0) or 0),
        }
        return {key: payload[key] for key in cls.ALLOWED_FIELDS}


class InstallerWorkItemSerializer:
    ALLOWED_FIELDS = {
        "addon_type_id",
        "qty_planned",
    }

    @classmethod
    def serialize_plan(cls, item) -> dict:
        payload = {
            "addon_type_id": item.addon_type_id,
            "qty_planned": item.qty_planned,
        }
        return {key: payload[key] for key in cls.ALLOWED_FIELDS}


class InstallerAddonFactSerializer:
    ALLOWED_FIELDS = {
        "id",
        "addon_type_id",
        "qty_done",
        "done_at",
        "comment",
        "source",
    }

    @classmethod
    def serialize(cls, fact) -> dict:
        payload = {
            "id": fact.id,
            "addon_type_id": fact.addon_type_id,
            "qty_done": fact.qty_done,
            "done_at": fact.done_at,
            "comment": fact.comment,
            "source": _enum_value(fact.source),
        }
        return {key: payload[key] for key in cls.ALLOWED_FIELDS}


class InstallerProjectSerializer:
    ALLOWED_FIELDS = {
        "id",
        "name",
        "address",
        "address_details",
        "waze_url",
        "whatsapp_url",
        "call_url",
        "developer",
        "contact_name",
        "contact_phone",
        "developer_phone_alt",
        "developer_whatsapp",
        "developer_company",
        "developer_notes",
        "status",
        "lifecycle_status",
        "health_status",
        "doors",
        "issues_open",
        "door_types_catalog",
        "reasons_catalog",
        "addons",
        "server_time",
    }

    @classmethod
    def serialize(
        cls,
        *,
        project,
        address: str | None,
        address_details: dict,
        waze_url: str | None,
        whatsapp_url: str | None,
        call_url: str | None,
        developer: dict,
        doors: list,
        issues_open: list[dict],
        door_types_catalog: list[dict],
        reasons_catalog: list[dict],
        addon_types: list[dict],
        addon_plan: list,
        addon_facts: list,
    ) -> dict:
        payload = {
            "id": project.id,
            "name": project.name,
            "address": address,
            "address_details": address_details,
            "waze_url": waze_url,
            "whatsapp_url": whatsapp_url,
            "call_url": call_url,
            "developer": developer,
            "contact_name": getattr(project, "contact_name", None),
            "contact_phone": getattr(project, "contact_phone", None),
            "developer_phone_alt": getattr(project, "developer_phone_alt", None),
            "developer_whatsapp": getattr(project, "developer_whatsapp", None),
            "developer_company": getattr(project, "developer_company", None),
            "developer_notes": getattr(project, "developer_notes", None),
            "status": _enum_value(project.status),
            "lifecycle_status": _enum_value(project.lifecycle_status),
            "health_status": _enum_value(project.health_status),
            "doors": [InstallerDoorSerializer.serialize(door) for door in doors],
            "issues_open": issues_open,
            "door_types_catalog": door_types_catalog,
            "reasons_catalog": reasons_catalog,
            "addons": {
                "types": addon_types,
                "plan": [
                    InstallerWorkItemSerializer.serialize_plan(item)
                    for item in addon_plan
                ],
                "facts": [
                    InstallerAddonFactSerializer.serialize(fact)
                    for fact in addon_facts
                ],
            },
            "server_time": datetime.now(timezone.utc),
        }
        return {key: payload[key] for key in cls.ALLOWED_FIELDS}
