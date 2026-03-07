from __future__ import annotations

import uuid
from decimal import Decimal

from app.shared.domain.errors import Conflict, NotFound
from app.modules.companies.application.limits_service import CompanyLimitsService
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.application.status_service import ProjectStatusService
from app.modules.sync.domain.enums import SyncChangeType


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
        project = ProjectORM(
            company_id=company_id,
            name=name,
            address=address,
            developer_company=kwargs.get("developer_company"),
            contact_name=kwargs.get("contact_name"),
            contact_phone=kwargs.get("contact_phone"),
            contact_email=kwargs.get("contact_email"),
            status=ProjectStatus.OK,
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

        for field in (
            "name",
            "address",
            "developer_company",
            "contact_name",
            "contact_phone",
            "contact_email",
        ):
            if field in kwargs and kwargs[field] is not None:
                setattr(project, field, kwargs[field])

        uow.projects.save(project)
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
