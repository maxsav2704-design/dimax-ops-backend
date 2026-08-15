from __future__ import annotations

import uuid
from decimal import Decimal

from app.shared.domain.errors import Conflict, NotFound, ValidationError
from app.shared.application.navigation import (
    build_project_address,
    is_valid_http_url,
    normalize_phone,
)
from app.modules.companies.application.limits_service import CompanyLimitsService
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.projects.domain.errors import InvalidPhone, InvalidWazeUrl
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.projects.domain.enums import ProjectLifecycleStatus, ProjectStatus
from app.modules.projects.application.status_service import ProjectStatusService
from app.modules.projects.application.sync_payload import build_project_sync_payload
from app.modules.doors.application.sync_payload import build_door_sync_payload
from app.modules.sync.domain.enums import SyncChangeType


def _clean_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _generate_project_code() -> str:
    return f"PRJ-{uuid.uuid4().hex[:6].upper()}"


ALLOWED_LIFECYCLE_TRANSITIONS: dict[
    ProjectLifecycleStatus, set[ProjectLifecycleStatus]
] = {
    ProjectLifecycleStatus.PLANNED: {
        ProjectLifecycleStatus.ACTIVE,
        ProjectLifecycleStatus.CANCELLED,
    },
    ProjectLifecycleStatus.ACTIVE: {
        ProjectLifecycleStatus.ON_HOLD,
        ProjectLifecycleStatus.COMPLETED,
        ProjectLifecycleStatus.CANCELLED,
    },
    ProjectLifecycleStatus.ON_HOLD: {
        ProjectLifecycleStatus.ACTIVE,
        ProjectLifecycleStatus.CANCELLED,
    },
    ProjectLifecycleStatus.COMPLETED: {ProjectLifecycleStatus.ACTIVE},
    ProjectLifecycleStatus.CANCELLED: {
        ProjectLifecycleStatus.PLANNED,
        ProjectLifecycleStatus.ACTIVE,
    },
}


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _coerce_lifecycle_status(value: object) -> ProjectLifecycleStatus:
    try:
        return ProjectLifecycleStatus(_enum_value(value).strip().upper())
    except ValueError as exc:
        raise ValidationError(
            "Unsupported project lifecycle status",
            field="lifecycle_status",
            meta={"value": str(value)},
        ) from exc


def _assert_lifecycle_transition(
    uow,
    *,
    company_id: uuid.UUID,
    project: ProjectORM,
    target: ProjectLifecycleStatus,
) -> None:
    current = _coerce_lifecycle_status(project.lifecycle_status)
    if target == current:
        return
    if target not in ALLOWED_LIFECYCLE_TRANSITIONS[current]:
        raise Conflict(
            f"Project cannot move from {current.value} to {target.value}",
            details={
                "field": "lifecycle_status",
                "from_status": current.value,
                "to_status": target.value,
            },
        )

    if target == ProjectLifecycleStatus.COMPLETED:
        terminal_statuses = {
            DoorStatus.INSTALLED,
            DoorStatus.CANCELLED,
            DoorStatus.LOCKED,
        }
        doors = uow.doors.list_by_project(
            company_id=company_id,
            project_id=project.id,
        )
        incomplete_count = sum(
            1
            for door in doors
            if getattr(door, "status", None) not in terminal_statuses
        )
        open_issue_count = len(
            uow.issues.list_open_by_project(
                company_id=company_id,
                project_id=project.id,
            )
        )
        if incomplete_count or open_issue_count:
            raise Conflict(
                "Project cannot be completed while work is unfinished",
                details={
                    "field": "lifecycle_status",
                    "incomplete_doors": incomplete_count,
                    "open_issues": open_issue_count,
                },
            )


def _normalize_project_payload(payload: dict) -> dict:
    normalized = dict(payload)

    if "code" in normalized:
        normalized["code"] = _clean_text(normalized.get("code")) or _generate_project_code()

    if "lifecycle_status" in normalized:
        normalized["lifecycle_status"] = _coerce_lifecycle_status(
            normalized["lifecycle_status"]
        ).value

    for field in (
        "name",
        "address",
        "developer_company",
        "contact_name",
        "contact_email",
        "developer_notes",
        "address_street",
        "address_building",
        "address_city",
        "address_entrance",
        "address_waze_url",
    ):
        if field in normalized:
            normalized[field] = _clean_text(normalized.get(field))

    for field in ("contact_phone", "developer_phone_alt", "developer_whatsapp"):
        if field in normalized:
            raw = _clean_text(normalized.get(field))
            if raw is None:
                normalized[field] = None
            else:
                phone = normalize_phone(raw)
                if not phone:
                    raise InvalidPhone(
                        "Phone number must be in international format",
                        details={"field": field},
                    )
                normalized[field] = phone

    if not is_valid_http_url(normalized.get("address_waze_url")):
        raise InvalidWazeUrl(
            "Waze URL must be a valid http or https address",
            details={"field": "address_waze_url"},
        )

    if normalized.get("planned_start_date") and normalized.get("planned_end_date"):
        if normalized["planned_end_date"] < normalized["planned_start_date"]:
            raise Conflict(
                "Planned end date must be on or after planned start date",
                details={"field": "planned_end_date"},
            )

    structured_address = build_project_address(
        address=normalized.get("address"),
        street=normalized.get("address_street"),
        building=normalized.get("address_building"),
        city=normalized.get("address_city"),
        entrance=normalized.get("address_entrance"),
    )
    normalized["address"] = structured_address or normalized.get("address") or ""
    return normalized


class ProjectUseCases:
    @staticmethod
    def create_project(
        uow,
        *,
        company_id: uuid.UUID,
        name: str,
        address: str,
        **kwargs,
    ) -> ProjectORM:
        CompanyLimitsService.assert_can_create_project(uow, company_id=company_id)
        payload = _normalize_project_payload({"name": name, "address": address, **kwargs})
        project = ProjectORM(
            company_id=company_id,
            name=payload["name"],
            code=payload.get("code"),
            address=payload["address"],
            planned_start_date=payload.get("planned_start_date"),
            planned_end_date=payload.get("planned_end_date"),
            developer_company=payload.get("developer_company"),
            contact_name=payload.get("contact_name"),
            contact_phone=payload.get("contact_phone"),
            contact_email=payload.get("contact_email"),
            developer_phone_alt=payload.get("developer_phone_alt"),
            developer_whatsapp=payload.get("developer_whatsapp"),
            developer_notes=payload.get("developer_notes"),
            address_street=payload.get("address_street"),
            address_building=payload.get("address_building"),
            address_city=payload.get("address_city"),
            address_entrance=payload.get("address_entrance"),
            address_lat=payload.get("address_lat"),
            address_lng=payload.get("address_lng"),
            address_waze_url=payload.get("address_waze_url"),
            status=ProjectStatus.OK,
            lifecycle_status=payload.get(
                "lifecycle_status", ProjectLifecycleStatus.ACTIVE.value
            ),
            health_status="NORMAL",
        )
        uow.projects.save(project)
        uow.session.flush()
        return project

    @staticmethod
    def update_project(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        **kwargs,
    ) -> ProjectORM:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found", details={"project_id": str(project_id)}
            )

        payload = _normalize_project_payload(kwargs)
        if "lifecycle_status" in payload:
            _assert_lifecycle_transition(
                uow,
                company_id=company_id,
                project=project,
                target=_coerce_lifecycle_status(payload["lifecycle_status"]),
            )

        for field in (
            "code",
            "name",
            "address",
            "planned_start_date",
            "planned_end_date",
            "lifecycle_status",
            "developer_company",
            "contact_name",
            "contact_phone",
            "contact_email",
            "developer_phone_alt",
            "developer_whatsapp",
            "developer_notes",
            "address_street",
            "address_building",
            "address_city",
            "address_entrance",
            "address_lat",
            "address_lng",
            "address_waze_url",
        ):
            if field in payload:
                setattr(project, field, payload[field])

        uow.projects.save(project)
        uow.session.flush()
        if "lifecycle_status" in payload:
            ProjectStatusService.recalc_and_set(
                uow=uow,
                company_id=company_id,
                project_id=project.id,
                emit_sync=False,
            )
        uow.sync_change_log.add_change(
            company_id=company_id,
            change_type=SyncChangeType.PROJECT_BASE,
            entity_id=project.id,
            project_id=project.id,
            installer_id=None,
            payload=build_project_sync_payload(project),
        )
        return project

    @staticmethod
    def delete_project(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found", details={"project_id": str(project_id)}
            )
        uow.projects.soft_delete(project)

    @staticmethod
    def import_doors(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        rows: list[dict],
        skip_existing: bool = False,
    ) -> tuple[int, int]:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found", details={"project_id": str(project_id)}
            )

        doors: list[DoorORM] = []
        skipped = 0
        for r in rows:
            door_type = uow.door_types.get(
                company_id=company_id,
                door_type_id=r["door_type_id"],
            )
            if door_type is None:
                raise NotFound(
                    "Door type not found",
                    details={"door_type_id": str(r["door_type_id"])},
                )
            if not door_type.is_active:
                raise Conflict(
                    "Door type is inactive",
                    details={"door_type_id": str(r["door_type_id"])},
                )
            if skip_existing and uow.doors.exists_by_project_unit_and_type(
                company_id=company_id,
                project_id=project_id,
                unit_label=str(r["unit_label"]).strip(),
                door_type_id=r["door_type_id"],
            ):
                skipped += 1
                continue
            doors.append(
                DoorORM(
                    company_id=company_id,
                    project_id=project_id,
                    door_type_id=r["door_type_id"],
                    unit_label=r["unit_label"],
                    our_price=Decimal(str(r["our_price"])),
                    order_number=r.get("order_number"),
                    house_number=r.get("house_number"),
                    floor_label=r.get("floor_label"),
                    apartment_number=r.get("apartment_number"),
                    location_code=r.get("location_code"),
                    door_marking=r.get("door_marking"),
                    status=DoorStatus.NOT_INSTALLED,
                    installer_id=None,
                    reason_id=None,
                    comment=None,
                    installed_at=None,
                    is_locked=False,
                )
            )

        CompanyLimitsService.assert_can_add_doors_to_project(
            uow,
            company_id=company_id,
            project_id=project_id,
            adding_count=len(doors),
        )
        uow.doors.add_many(doors)
        uow.session.flush()

        ProjectStatusService.recalc_and_set(
            uow=uow,
            company_id=company_id,
            project_id=project_id,
        )
        return len(doors), skipped

    @staticmethod
    def assign_installer_to_door(
        uow,
        *,
        company_id: uuid.UUID,
        door_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> None:
        door = uow.doors.get(company_id=company_id, door_id=door_id)
        if not door:
            raise NotFound("Door not found", details={"door_id": str(door_id)})

        if door.is_locked:
            raise Conflict(
                "Door is locked. Cannot reassign installer.",
                details={"door_id": str(door_id)},
            )

        installer = uow.installers.get(company_id=company_id, installer_id=installer_id)
        if installer is None or installer.deleted_at is not None or not installer.is_active:
            raise NotFound(
                "Installer not found",
                details={"installer_id": str(installer_id)},
            )

        old_installer_id = door.installer_id
        project_id = door.project_id
        door.installer_id = installer_id
        uow.doors.save(door)

        affected_door_ids = [door_id]
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if project is not None:
            uow.sync_change_log.add_change(
                company_id=company_id,
                change_type=SyncChangeType.PROJECT_BASE,
                entity_id=project_id,
                project_id=project_id,
                installer_id=installer_id,
                payload=build_project_sync_payload(project),
            )

        uow.sync_change_log.add_change(
            company_id=company_id,
            change_type=SyncChangeType.PROJECT_ASSIGNMENTS,
            entity_id=project_id,
            project_id=project_id,
            installer_id=None,
            payload={
                "kind": "assign_doors",
                "project_id": str(project_id),
                "affected_door_ids": [str(did) for did in affected_door_ids],
            },
        )
        uow.sync_change_log.add_change(
            company_id=company_id,
            change_type=SyncChangeType.PROJECT_ASSIGNMENTS,
            entity_id=project_id,
            project_id=project_id,
            installer_id=installer_id,
            payload={
                "kind": "assigned_to_you",
                "project_id": str(project_id),
                "affected_door_ids": [str(did) for did in affected_door_ids],
            },
        )
        uow.sync_change_log.add_change(
            company_id=company_id,
            change_type=SyncChangeType.DOOR,
            entity_id=door.id,
            project_id=project_id,
            installer_id=installer_id,
            payload=build_door_sync_payload(door),
        )
        if old_installer_id is not None:
            uow.sync_change_log.add_change(
                company_id=company_id,
                change_type=SyncChangeType.PROJECT_ASSIGNMENTS,
                entity_id=project_id,
                project_id=project_id,
                installer_id=old_installer_id,
                payload={
                    "kind": "removed_from_you",
                    "project_id": str(project_id),
                    "affected_door_ids": [str(did) for did in affected_door_ids],
                },
            )

    @staticmethod
    def assign_installer_to_doors(
        uow,
        *,
        company_id: uuid.UUID,
        door_ids: list[uuid.UUID],
        installer_id: uuid.UUID,
    ) -> tuple[int, int, list[uuid.UUID]]:
        unique_door_ids = list(dict.fromkeys(door_ids))
        skipped = len(door_ids) - len(unique_door_ids)

        installer = uow.installers.get(company_id=company_id, installer_id=installer_id)
        if installer is None or installer.deleted_at is not None or not installer.is_active:
            raise NotFound(
                "Installer not found",
                details={"installer_id": str(installer_id)},
            )

        doors = []
        for door_id in unique_door_ids:
            door = uow.doors.get(company_id=company_id, door_id=door_id)
            if not door:
                raise NotFound("Door not found", details={"door_id": str(door_id)})
            if door.is_locked:
                raise Conflict(
                    "Door is locked. Cannot reassign installer.",
                    details={"door_id": str(door_id)},
                )
            doors.append(door)

        project_ids = {door.project_id for door in doors}
        if len(project_ids) > 1:
            raise Conflict(
                "Bulk assignment must target doors from one project.",
                details={"project_ids": sorted(str(project_id) for project_id in project_ids)},
            )

        assigned_doors = []
        removed_by_installer: dict[uuid.UUID, list[uuid.UUID]] = {}
        for door in doors:
            old_installer_id = door.installer_id
            if old_installer_id == installer_id:
                skipped += 1
                continue

            door.installer_id = installer_id
            uow.doors.save(door)
            assigned_doors.append(door)
            if old_installer_id is not None:
                removed_by_installer.setdefault(old_installer_id, []).append(door.id)

        if not assigned_doors:
            return 0, skipped, []

        project_id = assigned_doors[0].project_id
        affected_door_ids = [door.id for door in assigned_doors]
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if project is not None:
            uow.sync_change_log.add_change(
                company_id=company_id,
                change_type=SyncChangeType.PROJECT_BASE,
                entity_id=project_id,
                project_id=project_id,
                installer_id=installer_id,
                payload=build_project_sync_payload(project),
            )

        uow.sync_change_log.add_change(
            company_id=company_id,
            change_type=SyncChangeType.PROJECT_ASSIGNMENTS,
            entity_id=project_id,
            project_id=project_id,
            installer_id=None,
            payload={
                "kind": "assign_doors",
                "project_id": str(project_id),
                "affected_door_ids": [str(did) for did in affected_door_ids],
            },
        )
        uow.sync_change_log.add_change(
            company_id=company_id,
            change_type=SyncChangeType.PROJECT_ASSIGNMENTS,
            entity_id=project_id,
            project_id=project_id,
            installer_id=installer_id,
            payload={
                "kind": "assigned_to_you",
                "project_id": str(project_id),
                "affected_door_ids": [str(did) for did in affected_door_ids],
            },
        )

        for door in assigned_doors:
            uow.sync_change_log.add_change(
                company_id=company_id,
                change_type=SyncChangeType.DOOR,
                entity_id=door.id,
                project_id=door.project_id,
                installer_id=installer_id,
                payload=build_door_sync_payload(door),
            )

        for old_installer_id, old_door_ids in removed_by_installer.items():
            uow.sync_change_log.add_change(
                company_id=company_id,
                change_type=SyncChangeType.PROJECT_ASSIGNMENTS,
                entity_id=project_id,
                project_id=project_id,
                installer_id=old_installer_id,
                payload={
                    "kind": "removed_from_you",
                    "project_id": str(project_id),
                    "affected_door_ids": [str(did) for did in old_door_ids],
                },
            )

        return len(assigned_doors), skipped, affected_door_ids
