from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM
from app.modules.audit.application.service import AuditService
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.api.admin_schemas import (
    AdminEarningsLedgerItemDTO,
    AdminEarningsLedgerResponseDTO,
    EarningsCorrectionResponseDTO,
    EarningsLedgerEntryDTO,
)
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.shared.domain.errors import Conflict, NotFound, ValidationError


_MONEY_QUANT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def _entry_dto(row: CompletedWorkORM) -> EarningsLedgerEntryDTO:
    return EarningsLedgerEntryDTO(
        id=row.id,
        entry_type=str(row.entry_type),
        correction_ref_id=row.correction_ref_id,
        completed_at=row.completed_at,
        quantity=Decimal(str(row.quantity)),
        rate_snapshot=Decimal(str(row.rate_snapshot)),
        amount_snapshot=Decimal(str(row.amount_snapshot)),
        reason=row.reason,
    )


def _admin_ledger_item_dto(
    row: CompletedWorkORM,
    *,
    project_name: str | None,
    door_label: str | None,
    door_code: str | None,
    addon_type_id: uuid.UUID | None,
    addon_type_name: str | None,
    addon_comment: str | None,
    installer_name: str | None,
    can_correct: bool,
) -> AdminEarningsLedgerItemDTO:
    return AdminEarningsLedgerItemDTO(
        id=row.id,
        entry_type=str(row.entry_type),
        correction_ref_id=row.correction_ref_id,
        completed_at=row.completed_at,
        quantity=Decimal(str(row.quantity)),
        rate_snapshot=Decimal(str(row.rate_snapshot)),
        amount_snapshot=Decimal(str(row.amount_snapshot)),
        reason=row.reason,
        work_kind=str(getattr(row, "work_kind", None) or "DOOR"),
        project_id=row.project_id,
        project_name=project_name,
        door_id=row.door_id,
        door_label=door_label,
        door_code=door_code,
        addon_fact_id=row.addon_fact_id,
        addon_type_id=addon_type_id,
        addon_type_name=addon_type_name,
        addon_comment=addon_comment,
        installer_id=row.installer_id,
        installer_name=installer_name,
        can_correct=can_correct,
    )


def _audit_entry_snapshot(row: CompletedWorkORM) -> dict:
    return {
        "id": str(row.id),
        "entry_type": str(row.entry_type),
        "project_id": str(row.project_id) if row.project_id else None,
        "door_id": str(row.door_id) if row.door_id else None,
        "addon_fact_id": str(row.addon_fact_id) if row.addon_fact_id else None,
        "installer_id": str(row.installer_id),
        "work_kind": str(getattr(row, "work_kind", None) or "DOOR"),
        "completed_at": row.completed_at.isoformat(),
        "quantity": str(_money(Decimal(str(row.quantity)))),
        "rate_snapshot": str(_money(Decimal(str(row.rate_snapshot)))),
        "amount_snapshot": str(_money(Decimal(str(row.amount_snapshot)))),
        "correction_ref_id": str(row.correction_ref_id) if row.correction_ref_id else None,
    }


class EarningsAdminApiService:
    @staticmethod
    def list_ledger(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
        entry_type: str | None,
        work_kind: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> AdminEarningsLedgerResponseDTO:
        assert uow.session is not None

        filters = [CompletedWorkORM.company_id == company_id]
        if installer_id is not None:
            filters.append(CompletedWorkORM.installer_id == installer_id)
        if project_id is not None:
            filters.append(CompletedWorkORM.project_id == project_id)
        if entry_type is not None:
            filters.append(CompletedWorkORM.entry_type == entry_type)
        if work_kind is not None:
            filters.append(CompletedWorkORM.work_kind == work_kind)
        if date_from is not None:
            filters.append(CompletedWorkORM.completed_at >= date_from)
        if date_to is not None:
            filters.append(CompletedWorkORM.completed_at < date_to)

        query = (
            uow.session.query(
                CompletedWorkORM,
                ProjectORM.name.label("project_name"),
                DoorORM.unit_label.label("door_label"),
                DoorORM.door_code.label("door_code"),
                ProjectAddonFactORM.addon_type_id.label("addon_type_id"),
                ProjectAddonFactORM.comment.label("addon_comment"),
                AddonTypeORM.name.label("addon_type_name"),
                InstallerORM.full_name.label("installer_name"),
            )
            .outerjoin(
                ProjectORM,
                (ProjectORM.company_id == company_id)
                & (ProjectORM.id == CompletedWorkORM.project_id),
            )
            .outerjoin(
                DoorORM,
                (DoorORM.company_id == company_id)
                & (DoorORM.id == CompletedWorkORM.door_id),
            )
            .outerjoin(
                ProjectAddonFactORM,
                (ProjectAddonFactORM.company_id == company_id)
                & (ProjectAddonFactORM.id == CompletedWorkORM.addon_fact_id),
            )
            .outerjoin(
                AddonTypeORM,
                (AddonTypeORM.company_id == company_id)
                & (AddonTypeORM.id == ProjectAddonFactORM.addon_type_id),
            )
            .outerjoin(
                InstallerORM,
                (InstallerORM.company_id == company_id)
                & (InstallerORM.id == CompletedWorkORM.installer_id),
            )
            .filter(*filters)
        )
        total = int(query.count())
        rows = (
            query.order_by(
                CompletedWorkORM.completed_at.desc(),
                CompletedWorkORM.id.desc(),
            )
            .limit(limit)
            .offset(offset)
            .all()
        )

        original_ids = [
            row.id
            for (
                row,
                _project_name,
                _door_label,
                _door_code,
                _addon_type_id,
                _addon_comment,
                _addon_type_name,
                _installer_name,
            ) in rows
            if str(row.entry_type) == "ORIGINAL"
        ]
        reversed_original_ids: set[uuid.UUID] = set()
        if original_ids:
            reversed_original_ids = set(
                uow.session.execute(
                    select(CompletedWorkORM.correction_ref_id).where(
                        CompletedWorkORM.company_id == company_id,
                        CompletedWorkORM.entry_type == "REVERSAL",
                        CompletedWorkORM.correction_ref_id.in_(original_ids),
                    )
                )
                .scalars()
                .all()
            )

        return AdminEarningsLedgerResponseDTO(
            items=[
                _admin_ledger_item_dto(
                    row,
                    project_name=project_name,
                    door_label=door_label,
                    door_code=door_code,
                    addon_type_id=addon_type_id,
                    addon_type_name=addon_type_name,
                    addon_comment=addon_comment,
                    installer_name=installer_name,
                    can_correct=(
                        str(row.entry_type) == "ORIGINAL"
                        and row.id not in reversed_original_ids
                    ),
                )
                for (
                    row,
                    project_name,
                    door_label,
                    door_code,
                    addon_type_id,
                    addon_comment,
                    addon_type_name,
                    installer_name,
                ) in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def ledger_export_csv(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
        entry_type: str | None,
        work_kind: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> str:
        ledger = EarningsAdminApiService.list_ledger(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            project_id=project_id,
            entry_type=entry_type,
            work_kind=work_kind,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "completed_at",
                "entry_type",
                "work_kind",
                "installer_id",
                "installer_name",
                "project_id",
                "project_name",
                "door_id",
                "door_label",
                "door_code",
                "addon_fact_id",
                "addon_type_id",
                "addon_type_name",
                "addon_comment",
                "quantity",
                "rate_snapshot",
                "amount_snapshot",
                "correction_ref_id",
                "can_correct",
                "reason",
            ]
        )
        for item in ledger.items:
            writer.writerow(
                [
                    str(item.id),
                    item.completed_at.isoformat(),
                    item.entry_type,
                    item.work_kind,
                    str(item.installer_id),
                    item.installer_name or "",
                    str(item.project_id) if item.project_id else "",
                    item.project_name or "",
                    str(item.door_id) if item.door_id else "",
                    item.door_label or "",
                    item.door_code or "",
                    str(item.addon_fact_id) if item.addon_fact_id else "",
                    str(item.addon_type_id) if item.addon_type_id else "",
                    item.addon_type_name or "",
                    item.addon_comment or "",
                    str(_money(Decimal(str(item.quantity)))),
                    str(_money(Decimal(str(item.rate_snapshot)))),
                    str(_money(Decimal(str(item.amount_snapshot)))),
                    str(item.correction_ref_id) if item.correction_ref_id else "",
                    "true" if item.can_correct else "false",
                    item.reason or "",
                ]
            )
        return output.getvalue()

    @staticmethod
    def create_correction(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        completed_work_id: uuid.UUID,
        rate_snapshot: Decimal,
        reason: str,
    ) -> EarningsCorrectionResponseDTO:
        assert uow.session is not None

        original = (
            uow.session.query(CompletedWorkORM)
            .filter(
                CompletedWorkORM.company_id == company_id,
                CompletedWorkORM.id == completed_work_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if original is None:
            raise NotFound(
                "Completed work entry not found",
                details={"completed_work_id": str(completed_work_id)},
            )

        if str(original.entry_type) != "ORIGINAL":
            raise ValidationError(
                "Only ORIGINAL completed work entries can be corrected",
                field="completed_work_id",
            )

        existing_correction_entry = uow.session.execute(
            select(CompletedWorkORM.id).where(
                CompletedWorkORM.company_id == company_id,
                CompletedWorkORM.entry_type.in_(("REVERSAL", "CORRECTION")),
                CompletedWorkORM.correction_ref_id == original.id,
            ).limit(1)
        ).scalar_one_or_none()
        if existing_correction_entry is not None:
            raise Conflict(
                "Completed work entry is already corrected",
                details={"completed_work_id": str(completed_work_id)},
            )

        quantity = _money(Decimal(str(original.quantity)))
        new_rate = _money(Decimal(str(rate_snapshot)))
        if new_rate <= 0:
            raise ValidationError(
                "Correction rate must be greater than zero",
                field="rate_snapshot",
            )
        new_amount = _money(new_rate * quantity)

        reversal = CompletedWorkORM(
            company_id=company_id,
            project_id=original.project_id,
            door_id=original.door_id,
            addon_fact_id=original.addon_fact_id,
            installer_id=original.installer_id,
            completed_at=original.completed_at,
            quantity=quantity,
            rate_snapshot=_money(-Decimal(str(original.rate_snapshot))),
            amount_snapshot=_money(-Decimal(str(original.amount_snapshot))),
            work_kind=str(getattr(original, "work_kind", None) or "DOOR"),
            entry_type="REVERSAL",
            correction_ref_id=original.id,
            reason=reason,
        )
        correction = CompletedWorkORM(
            company_id=company_id,
            project_id=original.project_id,
            door_id=original.door_id,
            addon_fact_id=original.addon_fact_id,
            installer_id=original.installer_id,
            completed_at=original.completed_at,
            quantity=quantity,
            rate_snapshot=new_rate,
            amount_snapshot=new_amount,
            work_kind=str(getattr(original, "work_kind", None) or "DOOR"),
            entry_type="CORRECTION",
            correction_ref_id=original.id,
            reason=reason,
        )
        uow.session.add(reversal)
        uow.session.add(correction)
        uow.session.flush()

        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="completed_work",
            entity_id=original.id,
            action="EARNINGS_CORRECTION",
            reason=reason,
            before={"original": _audit_entry_snapshot(original)},
            after={
                "reversal": _audit_entry_snapshot(reversal),
                "correction": _audit_entry_snapshot(correction),
            },
        )

        return EarningsCorrectionResponseDTO(
            original=_entry_dto(original),
            reversal=_entry_dto(reversal),
            correction=_entry_dto(correction),
        )
