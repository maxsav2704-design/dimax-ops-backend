from __future__ import annotations

import uuid

from app.shared.domain.errors import Forbidden, NotFound
from app.shared.application.navigation import (
    build_call_url,
    build_project_address,
    format_coordinate,
    resolve_locale,
    build_waze_url,
    build_whatsapp_url,
)
from app.modules.projects.application.installer_serializers import (
    InstallerProjectSerializer,
)


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


class ProjectInstallerService:
    @staticmethod
    def _project_whatsapp_message(project, locale: str = "en") -> str | None:
        code = str(getattr(project, "code", "") or "").strip()
        name = str(getattr(project, "name", "") or "").strip()
        if not name and not code:
            return None
        project_ref = f"{name} ({code})" if name and code else name or code
        normalized_locale = resolve_locale(locale)
        if normalized_locale == "ru":
            return f"Добрый день, по проекту {project_ref}"
        if normalized_locale == "he":
            return f"שלום, בקשר לפרויקט {project_ref}"
        return f"Hello, regarding project {project_ref}"

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
        locale: str = "en",
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
        address_lat = format_coordinate(getattr(project, "address_lat", None))
        address_lng = format_coordinate(getattr(project, "address_lng", None))
        whatsapp_phone = getattr(project, "developer_whatsapp", None) or getattr(project, "contact_phone", None)

        address_details = {
            "street": getattr(project, "address_street", None),
            "building": getattr(project, "address_building", None),
            "city": getattr(project, "address_city", None),
            "entrance": getattr(project, "address_entrance", None),
            "lat": address_lat,
            "lng": address_lng,
            "waze_url": getattr(project, "address_waze_url", None),
            "waze_deep_link": build_waze_url(
                address=project_address,
                lat=address_lat,
                lng=address_lng,
                manual_url=getattr(project, "address_waze_url", None),
            ),
        }
        waze_url = build_waze_url(
            address=project_address,
            lat=address_lat,
            lng=address_lng,
            manual_url=getattr(project, "address_waze_url", None),
        )
        whatsapp_url = build_whatsapp_url(
            phone=whatsapp_phone,
            message=ProjectInstallerService._project_whatsapp_message(project, locale=locale),
        )
        call_url = build_call_url(phone=getattr(project, "contact_phone", None))

        return InstallerProjectSerializer.serialize(
            project=project,
            address=project_address,
            address_details=address_details,
            waze_url=waze_url,
            whatsapp_url=whatsapp_url,
            call_url=call_url,
            developer={
                "name": getattr(project, "developer_company", None),
                "contact_name": getattr(project, "contact_name", None),
                "phone": getattr(project, "contact_phone", None),
                "phone_alt": getattr(project, "developer_phone_alt", None),
                "whatsapp": getattr(project, "developer_whatsapp", None),
                "notes": getattr(project, "developer_notes", None),
                "whatsapp_deep_link": whatsapp_url,
                "call_deep_link": call_url,
            },
            doors=my_doors,
            issues_open=[
                {
                    "id": i.id,
                    "door_id": i.door_id,
                    "status": _status_value(i.status),
                    "title": i.title,
                    "details": i.details,
                }
                for i in issues
            ],
            door_types_catalog=[
                {"id": x.id, "code": x.code, "name": x.name} for x in door_types
            ],
            reasons_catalog=[
                {"id": x.id, "code": x.code, "name": x.name} for x in reasons
            ],
            addon_types=[
                {"id": t.id, "name": t.name, "unit": t.unit} for t in addon_types
            ],
            addon_plan=addon_plan,
            addon_facts=addon_facts,
        )
