from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from app.api.v1.guards import require_door_owned_by_installer
from app.modules.doors.application.installer_service import InstallerDoorService
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.domain.errors import DoorNotAssigned, InvalidTransition
from app.modules.doors.infrastructure.history_models import DoorStatusHistoryORM
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.doors.infrastructure.repositories import DoorRepository
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.domain.enums import UserRole
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.modules.projects.application.use_cases import ProjectUseCases
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.shared.domain.errors import Conflict, NotFound
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork


@pytest.fixture()
def assignment_case(db_session, company_id, make_user, make_installer, make_door_type):
    user = make_user(role=UserRole.INSTALLER, password="Assignment-check-2026!")
    first = make_installer(full_name="First installer")
    second = make_installer(full_name="Second installer")
    first.user_id = user.id
    door_type = make_door_type()
    project = ProjectORM(
        company_id=company_id, name="Atomic assignment", address="Test building A", status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()
    door = DoorORM(
        company_id=company_id, project_id=project.id, door_type_id=door_type.id,
        unit_label="A-101", our_price=Decimal("1000.00"),
        installer_id=first.id, status=DoorStatus.IN_PROGRESS, is_locked=False,
    )
    db_session.add(door)
    for installer, price in ((first, "250.00"), (second, "400.00")):
        db_session.add(InstallerRateORM(
            company_id=company_id, installer_id=installer.id, door_type_id=door_type.id,
            effective_from=datetime.now(timezone.utc) - timedelta(days=1), price=Decimal(price),
        ))
    db_session.commit()
    return SimpleNamespace(
        company_id=company_id, door_id=door.id, first_id=first.id,
        second_id=second.id, user_id=user.id, email=user.email,
    )


def _complete(uow, case):
    return InstallerDoorService.change_status(
        uow, company_id=case.company_id, actor_user_id=case.user_id,
        installer_id=case.first_id, door_id=case.door_id, to_status=DoorStatus.INSTALLED,
    )


def _reassign(uow, case, *, bulk=False):
    if bulk:
        return ProjectUseCases.assign_installer_to_doors(
            uow, company_id=case.company_id, door_ids=[case.door_id], installer_id=case.second_id,
        )
    return ProjectUseCases.assign_installer_to_door(
        uow, company_id=case.company_id, door_id=case.door_id, installer_id=case.second_id,
    )


@pytest.mark.parametrize("bulk", [False, True])
def test_assignment_rechecks_a_door_completed_after_initial_read(assignment_case, bulk):
    case = assignment_case
    with SqlAlchemyUnitOfWork() as stale:
        cached = stale.doors.get(company_id=case.company_id, door_id=case.door_id)
        assert cached.is_locked is False
        with SqlAlchemyUnitOfWork() as completion:
            _complete(completion, case)
        assert cached.is_locked is False
        with pytest.raises(Conflict):
            _reassign(stale, case, bulk=bulk)


def test_completion_rechecks_assignment_after_initial_read(assignment_case, db_session):
    case = assignment_case
    with SqlAlchemyUnitOfWork() as stale:
        cached = stale.doors.get(company_id=case.company_id, door_id=case.door_id)
        assert cached.installer_id == case.first_id
        with SqlAlchemyUnitOfWork() as assignment:
            _reassign(assignment, case)
        assert cached.installer_id == case.first_id
        with pytest.raises(DoorNotAssigned):
            _complete(stale, case)
    assert db_session.query(CompletedWorkORM).filter(CompletedWorkORM.door_id == case.door_id).count() == 0


@pytest.mark.parametrize("action", ["install", "not-installed"])
def test_legacy_action_rechecks_assignment_after_request_guard(
    assignment_case, client_raw, db_session, make_reason, action,
):
    case = assignment_case
    login = client_raw.post("/api/v1/auth/login", json={
        "company_id": str(case.company_id), "email": case.email,
        "password": "Assignment-check-2026!", "device_id": "assignment-regression",
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    reason = make_reason()
    with SqlAlchemyUnitOfWork() as assignment:
        _reassign(assignment, case)

    # Model a guard that passed before the administrator committed reassignment.
    client_raw.app.dependency_overrides[require_door_owned_by_installer] = lambda: case.first_id
    try:
        response = client_raw.post(
            f"/api/v1/installer/doors/{case.door_id}/{action}", headers=headers,
            json={"reason_id": str(reason.id)} if action == "not-installed" else None,
        )
    finally:
        client_raw.app.dependency_overrides.pop(require_door_owned_by_installer, None)
    assert response.status_code == 403, response.text
    assert db_session.query(CompletedWorkORM).filter(CompletedWorkORM.door_id == case.door_id).count() == 0
    db_session.expire_all()
    door = db_session.get(DoorORM, case.door_id)
    assert door.installer_id == case.second_id
    assert door.status == DoorStatus.IN_PROGRESS


def test_completion_rechecks_project_deleted_after_initial_read(assignment_case, db_session):
    case = assignment_case
    with SqlAlchemyUnitOfWork() as stale:
        cached = stale.doors.get(company_id=case.company_id, door_id=case.door_id)
        with SqlAlchemyUnitOfWork() as deletion:
            ProjectUseCases.delete_project(deletion, company_id=case.company_id, project_id=cached.project_id)
        with pytest.raises(NotFound):
            _complete(stale, case)
        assert stale.doors.get(company_id=case.company_id, door_id=case.door_id) is cached
    assert db_session.query(CompletedWorkORM).filter(CompletedWorkORM.door_id == case.door_id).count() == 0


@pytest.mark.parametrize("action", ["install", "not-installed"])
def test_legacy_action_rechecks_deleted_project_after_request_guard(
    assignment_case, client_raw, db_session, make_reason, action,
):
    case = assignment_case
    login = client_raw.post("/api/v1/auth/login", json={
        "company_id": str(case.company_id), "email": case.email,
        "password": "Assignment-check-2026!", "device_id": "deletion-regression",
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    reason = make_reason()
    door = db_session.get(DoorORM, case.door_id)
    with SqlAlchemyUnitOfWork() as deletion:
        ProjectUseCases.delete_project(deletion, company_id=case.company_id, project_id=door.project_id)

    client_raw.app.dependency_overrides[require_door_owned_by_installer] = lambda: case.first_id
    try:
        response = client_raw.post(
            f"/api/v1/installer/doors/{case.door_id}/{action}", headers=headers,
            json={"reason_id": str(reason.id)} if action == "not-installed" else None,
        )
    finally:
        client_raw.app.dependency_overrides.pop(require_door_owned_by_installer, None)
    assert response.status_code == 404, response.text
    db_session.refresh(door)
    assert (door.status, door.is_locked, door.version) == (DoorStatus.IN_PROGRESS, False, 0)
    assert db_session.query(CompletedWorkORM).filter(CompletedWorkORM.door_id == case.door_id).count() == 0
    assert db_session.query(DoorStatusHistoryORM).filter(DoorStatusHistoryORM.door_id == case.door_id).count() == 0


def test_installer_write_read_locks_project_until_transaction_end(assignment_case):
    case = assignment_case
    with SqlAlchemyUnitOfWork() as writer:
        door = writer.doors.get(
            company_id=case.company_id, door_id=case.door_id,
            for_update=True, active_project_only=True,
        )
        project_id = door.project_id
        with SqlAlchemyUnitOfWork() as contender:
            with pytest.raises(OperationalError) as error:
                contender.session.query(ProjectORM).filter(ProjectORM.id == project_id).with_for_update(nowait=True).one()
            assert error.value.orig.pgcode == "55P03"
            contender.rollback()
    with SqlAlchemyUnitOfWork() as released:
        assert released.session.query(ProjectORM).filter(ProjectORM.id == project_id).with_for_update(nowait=True).one()


def test_write_read_holds_row_lock_until_transaction_end(assignment_case):
    case = assignment_case
    with SqlAlchemyUnitOfWork() as writer:
        writer.doors.get(company_id=case.company_id, door_id=case.door_id, for_update=True)
        with SqlAlchemyUnitOfWork() as contender:
            with pytest.raises(OperationalError) as error:
                contender.session.query(DoorORM).filter(DoorORM.id == case.door_id).with_for_update(nowait=True).one()
            assert error.value.orig.pgcode == "55P03"
            contender.rollback()
    with SqlAlchemyUnitOfWork() as released:
        assert released.session.query(DoorORM).filter(DoorORM.id == case.door_id).with_for_update(nowait=True).one()


def test_simultaneous_completions_create_one_accrual_and_transition(
    assignment_case, db_session, monkeypatch,
):
    case = assignment_case
    original_get = DoorRepository.get

    def slow_get(self, **kwargs):
        door = original_get(self, **kwargs)
        time.sleep(0.2)
        return door

    monkeypatch.setattr(DoorRepository, "get", slow_get)
    start = threading.Barrier(2)

    def complete():
        start.wait(timeout=10)
        try:
            with SqlAlchemyUnitOfWork() as uow:
                _complete(uow, case)
        except InvalidTransition:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = [executor.submit(complete) for _ in range(2)]
        assert sorted(attempt.result(timeout=60) for attempt in attempts) == [False, True]

    work = db_session.query(CompletedWorkORM).filter(CompletedWorkORM.door_id == case.door_id).one()
    assert work.installer_id == case.first_id
    assert work.amount_snapshot == Decimal("250.00")
    assert db_session.query(DoorStatusHistoryORM).filter(DoorStatusHistoryORM.door_id == case.door_id).count() == 1
    db_session.expire_all()
    door = db_session.get(DoorORM, case.door_id)
    assert door.version == 1
    assert door.is_locked is True


def test_real_auth_assignment_visibility_completion_and_payroll_reconcile(
    assignment_case, client_raw, db_session, make_user,
):
    case = assignment_case
    admin = make_user(role=UserRole.ADMIN, password="Assignment-check-2026!")
    second_user = make_user(role=UserRole.INSTALLER, password="Assignment-check-2026!")
    db_session.get(InstallerORM, case.second_id).user_id = second_user.id
    first_door = db_session.get(DoorORM, case.door_id)
    project_id = str(first_door.project_id)
    second_door = DoorORM(
        company_id=case.company_id, project_id=first_door.project_id,
        door_type_id=first_door.door_type_id, unit_label="B-101",
        our_price=Decimal("1200.00"), status=DoorStatus.NOT_INSTALLED, is_locked=False,
    )
    db_session.add(second_door)
    db_session.commit()

    def login(email):
        response = client_raw.post("/api/v1/auth/login", json={
            "company_id": str(case.company_id), "email": email,
            "password": "Assignment-check-2026!", "device_id": "payroll-regression",
        })
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    owner = login(admin.email)
    first = login(case.email)
    second = login(second_user.email)
    assigned = client_raw.post(
        "/api/v1/admin/projects/doors/bulk-assign-installer", headers=owner,
        json={"door_ids": [str(second_door.id)], "installer_id": str(case.second_id)},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assigned"] == 1

    for headers, own_id in ((first, case.door_id), (second, second_door.id)):
        project = client_raw.get(f"/api/v1/installer/projects/{project_id}", headers=headers)
        assert project.status_code == 200, project.text
        assert {door["id"] for door in project.json()["doors"]} == {str(own_id)}

    forbidden = client_raw.patch(
        f"/api/v1/installer/doors/{second_door.id}/status", headers=first,
        json={"status": "IN_PROGRESS"},
    )
    assert forbidden.status_code == 403, forbidden.text
    for headers, door_id, statuses in (
        (first, case.door_id, ["INSTALLED"]),
        (second, second_door.id, ["IN_PROGRESS", "INSTALLED"]),
    ):
        path = f"/api/v1/installer/doors/{door_id}/status"
        for status in statuses:
            response = client_raw.patch(path, headers=headers, json={"status": status})
            assert response.status_code == 200, response.text
        repeated = client_raw.patch(path, headers=headers, json={"status": "INSTALLED"})
        assert repeated.status_code == 422, repeated.text

    for headers, total in ((first, "250.00"), (second, "400.00")):
        summary = client_raw.get("/api/v1/installer/earnings/summary?period=day", headers=headers)
        assert summary.status_code == 200, summary.text
        assert Decimal(summary.json()["total"]) == Decimal(total)

    report = client_raw.get(f"/api/v1/admin/reports/project-plan-fact/{project_id}", headers=owner)
    assert report.status_code == 200, report.text
    result = report.json()
    assert result["installed_doors"] == result["total_doors"] == 2
    assert Decimal(result["actual_payroll_total"]) == Decimal("650.00")
    assert Decimal(result["actual_revenue_total"]) == Decimal("2200.00")
    assert Decimal(result["actual_profit_total"]) == Decimal("1550.00")
    assert db_session.query(CompletedWorkORM).filter(CompletedWorkORM.company_id == case.company_id).count() == 2
