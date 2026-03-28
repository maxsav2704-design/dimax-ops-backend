from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.shared.domain.errors import Forbidden, NotFound
from app.shared.application.navigation import (
    build_call_url,
    build_project_address,
    build_waze_url,
    build_whatsapp_url,
)


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


class ProjectInstallerService:
    @staticmethod
    def list_my_projects(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> dict:
        project_ids = uow.doors.list_project_ids_for_installer(
            company_id=company_id, installer_id=installer_id
        )
        projects = uow.projects.list_by_ids(company_id=company_id, ids=project_ids)
        return {
            "items": [
                {
                    "id": p.id,
                    "name": p.name,
                    "address": (
                        build_project_address(
                            address=getattr(p, "address", None),
                            street=getattr(p, "address_street", None),
                            building=getattr(p, "address_building", None),
                            city=getattr(p, "address_city", None),
                            entrance=getattr(p, "address_entrance", None),
                        )
                        or ""
                    ),
                    "status": _status_value(p.status),
                    "waze_url": build_waze_url(
                        address=build_project_address(
                            address=getattr(p, "address", None),
                            street=getattr(p, "address_street", None),
                            building=getattr(p, "address_building", None),
                            city=getattr(p, "address_city", None),
                            entrance=getattr(p, "address_entrance", None),
                        ),
                        lat=getattr(p, "address_lat", None),
                        lng=getattr(p, "address_lng", None),
                        manual_url=getattr(p, "address_waze_url", None),
                    ),
                }
                for p in projects
            ]
        }

    @staticmethod
    def project_details(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> dict:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound("Project not found", details={"project_id": str(project_id)})

        my_doors = uow.doors.list_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )
        if not my_doors:
            raise Forbidden("Project is not assigned to this installer")

        issues = uow.issues.list_open_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )

        addon_types = uow.addon_types.list_active(company_id=company_id)
        addon_plan = uow.addon_plans.list_by_project(
            company_id=company_id, project_id=project_id
        )
        addon_facts = uow.addon_facts.list_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )
        door_types = uow.door_types.list_active(company_id=company_id)
        reasons = uow.reasons.list_active(company_id=company_id)

        project_address = build_project_address(
            address=getattr(project, "address", None),
            street=getattr(project, "address_street", None),
            building=getattr(project, "address_building", None),
            city=getattr(project, "address_city", None),
            entrance=getattr(project, "address_entrance", None),
        )
        whatsapp_phone = getattr(project, "developer_whatsapp", None) or getattr(project, "contact_phone", None)
        whatsapp_message = " · ".join(
            part for part in [getattr(project, "code", None), getattr(project, "name", None)] if part
        )

        return {
            "id": project.id,
            "name": project.name,
            "address": project_address,
            "waze_url": build_waze_url(
                address=project_address,
                lat=getattr(project, "address_lat", None),
                lng=getattr(project, "address_lng", None),
                manual_url=getattr(project, "address_waze_url", None),
            ),
            "whatsapp_url": build_whatsapp_url(
                phone=whatsapp_phone,
                message=whatsapp_message or None,
            ),
            "call_url": build_call_url(phone=getattr(project, "contact_phone", None)),
            "contact_name": getattr(project, "contact_name", None),
            "contact_phone": getattr(project, "contact_phone", None),
            "developer_company": getattr(project, "developer_company", None),
            "developer_notes": getattr(project, "developer_notes", None),
            "status": _status_value(project.status),
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
                    "reason_id": d.reason_id,
                    "comment": d.comment,
                    "is_locked": d.is_locked,
                }
                for d in my_doors
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
            "door_types_catalog": [
                {"id": x.id, "code": x.code, "name": x.name} for x in door_types
            ],
            "reasons_catalog": [
                {"id": x.id, "code": x.code, "name": x.name} for x in reasons
            ],
            "addons": {
                "types": [
                    {"id": t.id, "name": t.name, "unit": t.unit} for t in addon_types
                ],
                "plan": [
                    {
                        "addon_type_id": x.addon_type_id,
                        "qty_planned": x.qty_planned,
                        "client_price": x.client_price,
                        "installer_price": x.installer_price,
                    }
                    for x in addon_plan
                ],
                "facts": [
                    {
                        "id": f.id,
                        "addon_type_id": f.addon_type_id,
                        "qty_done": f.qty_done,
                        "done_at": f.done_at,
                        "comment": f.comment,
                        "source": _status_value(f.source),
                    }
                    for f in addon_facts
                ],
            },
            "server_time": datetime.now(timezone.utc),
        }
