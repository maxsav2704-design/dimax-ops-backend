from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def _seed_door(db_session, *, company_id, make_installer, make_door_type):
    installer = make_installer(full_name="Financial Constraint Installer")
    door_type = make_door_type(name="Financial Constraint Door")
    project = ProjectORM(
        company_id=company_id,
        name=f"Financial Constraints {uuid.uuid4().hex[:8]}",
        address="Constraint test address",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="FC-01",
        our_price=Decimal("100.00"),
        installer_rate_snapshot=Decimal("40.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer.id,
        installed_at=datetime.now(timezone.utc),
        is_locked=True,
        surcharge_pct=Decimal("100.00"),
        version=1,
    )
    db_session.add(door)
    db_session.commit()
    return project.id, door.id, installer.id, door_type.id


def test_database_rejects_invalid_completed_work_sign(
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    project_id, door_id, installer_id, _door_type_id = _seed_door(
        db_session,
        company_id=company_id,
        make_installer=make_installer,
        make_door_type=make_door_type,
    )
    db_session.add(
        CompletedWorkORM(
            company_id=company_id,
            project_id=project_id,
            door_id=door_id,
            installer_id=installer_id,
            completed_at=datetime.now(timezone.utc),
            quantity=Decimal("1.00"),
            rate_snapshot=Decimal("-40.00"),
            amount_snapshot=Decimal("-40.00"),
            work_kind="DOOR",
            entry_type="ORIGINAL",
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert _constraint_name(exc_info.value) == "ck_completed_work_amount_sign"
    db_session.rollback()


def test_database_rejects_negative_addon_price(db_session, company_id):
    db_session.add(
        AddonTypeORM(
            company_id=company_id,
            name="Invalid negative price",
            unit="pcs",
            default_client_price=Decimal("10.00"),
            default_installer_price=Decimal("-1.00"),
            is_active=True,
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert _constraint_name(exc_info.value) == "ck_addon_types_prices"
    db_session.rollback()


def test_database_rejects_zero_installer_snapshot(
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    project_id, _door_id, installer_id, door_type_id = _seed_door(
        db_session,
        company_id=company_id,
        make_installer=make_installer,
        make_door_type=make_door_type,
    )
    db_session.add(
        DoorORM(
            company_id=company_id,
            project_id=project_id,
            door_type_id=door_type_id,
            unit_label="FC-02",
            our_price=Decimal("100.00"),
            installer_rate_snapshot=Decimal("0.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer_id,
            is_locked=False,
            surcharge_pct=Decimal("100.00"),
            version=0,
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert _constraint_name(exc_info.value) == "ck_doors_installer_rate_positive"
    db_session.rollback()


@pytest.mark.parametrize(
    ("entry_type", "rate_snapshot", "amount_snapshot"),
    [
        ("REVERSAL", Decimal("-40.00"), Decimal("-40.00")),
        ("CORRECTION", Decimal("55.00"), Decimal("55.00")),
    ],
)
def test_database_rejects_duplicate_payroll_correction_entry_type(
    db_session,
    company_id,
    make_installer,
    make_door_type,
    entry_type,
    rate_snapshot,
    amount_snapshot,
):
    project_id, door_id, installer_id, _door_type_id = _seed_door(
        db_session,
        company_id=company_id,
        make_installer=make_installer,
        make_door_type=make_door_type,
    )
    original = CompletedWorkORM(
        company_id=company_id,
        project_id=project_id,
        door_id=door_id,
        installer_id=installer_id,
        completed_at=datetime.now(timezone.utc),
        quantity=Decimal("1.00"),
        rate_snapshot=Decimal("40.00"),
        amount_snapshot=Decimal("40.00"),
        work_kind="DOOR",
        entry_type="ORIGINAL",
    )
    db_session.add(original)
    db_session.flush()

    def correction_entry() -> CompletedWorkORM:
        return CompletedWorkORM(
            company_id=company_id,
            project_id=project_id,
            door_id=door_id,
            installer_id=installer_id,
            completed_at=original.completed_at,
            quantity=Decimal("1.00"),
            rate_snapshot=rate_snapshot,
            amount_snapshot=amount_snapshot,
            work_kind="DOOR",
            entry_type=entry_type,
            correction_ref_id=original.id,
            reason="Concurrent finance correction",
        )

    db_session.add(correction_entry())
    db_session.flush()
    db_session.add(correction_entry())

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert (
        _constraint_name(exc_info.value)
        == "uq_completed_work_correction_ref_entry_type"
    )
    db_session.rollback()
