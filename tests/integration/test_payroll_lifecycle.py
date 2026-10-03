from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.modules.doors.application.commands import AdminOverrideDoor
from app.modules.doors.application.use_cases import DoorUseCases
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.application.admin_api_service import EarningsAdminApiService
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.domain.enums import UserRole
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.modules.rates.infrastructure.price_lists_repository import FactoryPriceListsRepository
from app.shared.domain.errors import Conflict
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork


INSTALLED_AT = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
CANCELLED_AT = datetime(2026, 9, 11, 9, tzinfo=timezone.utc)


@pytest.fixture()
def payroll_case(client_raw, db_session, company_id, make_user, make_installer, make_door_type, make_reason):
    password = "Payroll-lifecycle-test-2026!"
    owner = make_user(role=UserRole.ADMIN, password=password)
    user = make_user(role=UserRole.INSTALLER, password=password)
    installer = make_installer(full_name="Payroll lifecycle installer")
    installer.user_id = user.id
    door_type = make_door_type()
    reason = make_reason()
    project = ProjectORM(
        company_id=company_id, name="Payroll lifecycle", address="Test building A",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()
    door = DoorORM(
        company_id=company_id, project_id=project.id, door_type_id=door_type.id,
        installer_id=installer.id, unit_label="A-101", our_price=Decimal("1000.00"),
        status=DoorStatus.NOT_INSTALLED, is_locked=False,
    )
    rate = InstallerRateORM(
        company_id=company_id, installer_id=installer.id, door_type_id=door_type.id,
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc), price=Decimal("250.00"),
    )
    db_session.add_all([door, rate])
    db_session.commit()

    def login(email):
        response = client_raw.post("/api/v1/auth/login", json={
            "company_id": str(company_id), "email": email, "password": password,
            "device_id": "payroll-lifecycle",
        })
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    case = SimpleNamespace(
        client=client_raw, session=db_session, company_id=company_id,
        project_id=project.id, door_id=door.id, installer_id=installer.id,
        reason_id=reason.id, owner_id=owner.id, owner=login(owner.email), installer=login(user.email),
    )
    with patch("app.modules.doors.application.use_cases.utcnow", return_value=INSTALLED_AT):
        response = client_raw.post(f"/api/v1/installer/doors/{door.id}/install", headers=case.installer)
    assert response.status_code == 200, response.text
    case.original_id = db_session.query(CompletedWorkORM.id).filter(
        CompletedWorkORM.door_id == door.id,
    ).scalar()
    return case


def _correct(case, entry_id=None, rate="300.00"):
    response = case.client.post("/api/v1/admin/earnings/corrections", headers=case.owner, json={
        "completed_work_id": str(entry_id or case.original_id),
        "rate_snapshot": rate, "reason": "Test approved rate correction",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _cancel(case, at=CANCELLED_AT):
    with patch("app.modules.doors.application.completion.utcnow", return_value=at):
        response = case.client.post(f"/api/v1/admin/doors/{case.door_id}/override", headers=case.owner, json={
            "new_status": "NOT_INSTALLED", "reason_id": str(case.reason_id),
            "override_reason": "Test cancellation of incorrect completion",
        })
    assert response.status_code == 200, response.text


def _summary(case, period, day):
    response = case.client.get(
        f"/api/v1/installer/earnings/summary?period={period}&date={day}", headers=case.installer,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _report(case):
    response = case.client.get(
        f"/api/v1/admin/reports/project-plan-fact/{case.project_id}", headers=case.owner,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _ledger_total(case):
    rows = case.session.query(CompletedWorkORM).filter(CompletedWorkORM.company_id == case.company_id).all()
    return sum((row.amount_snapshot for row in rows), Decimal("0"))


@pytest.mark.parametrize("corrected", [False, True])
@pytest.mark.parametrize("same_day", [False, True])
def test_cancellation_reconciles_daily_monthly_and_project_totals(payroll_case, corrected, same_day):
    case = payroll_case
    amount = Decimal("300.00") if corrected else Decimal("250.00")
    if corrected:
        _correct(case)
    at = INSTALLED_AT if same_day else CANCELLED_AT
    _cancel(case, at)
    _cancel(case, at)  # A repeated cancellation cannot debit the installer twice.

    assert _ledger_total(case) == Decimal("0.00")
    assert Decimal(_summary(case, "month", "2026-09-11")["total"]) == Decimal("0.00")
    if same_day:
        assert Decimal(_summary(case, "day", "2026-09-10")["total"]) == Decimal("0.00")
    else:
        assert Decimal(_summary(case, "day", "2026-09-10")["total"]) == amount
        assert Decimal(_summary(case, "day", "2026-09-11")["total"]) == -amount
    report = _report(case)
    assert report["installed_doors"] == 0
    assert Decimal(report["actual_payroll_total"]) == Decimal("0.00")
    assert Decimal(report["actual_revenue_total"]) == Decimal("0.00")


def test_reaffirming_corrected_installation_does_not_create_another_accrual(payroll_case):
    case = payroll_case
    _correct(case)
    for _ in range(2):
        response = case.client.post(f"/api/v1/admin/doors/{case.door_id}/override", headers=case.owner, json={
            "new_status": "INSTALLED", "override_reason": "Test reaffirm existing completion",
        })
        assert response.status_code == 200, response.text
    assert _ledger_total(case) == Decimal("300.00")
    assert case.session.query(CompletedWorkORM).filter(CompletedWorkORM.door_id == case.door_id).count() == 3
    case.session.expire_all()
    assert case.session.get(DoorORM, case.door_id).installed_at == INSTALLED_AT
    report = _report(case)
    assert Decimal(report["actual_payroll_total"]) == Decimal("300.00")
    assert Decimal(report["actual_revenue_total"]) == Decimal("1000.00")


def test_reinstallation_after_corrected_cancellation_uses_one_new_accrual(payroll_case):
    case = payroll_case
    _correct(case)
    _cancel(case)
    with patch("app.modules.doors.application.use_cases.utcnow", return_value=CANCELLED_AT):
        response = case.client.post(f"/api/v1/installer/doors/{case.door_id}/install", headers=case.installer)
    assert response.status_code == 200, response.text
    assert _ledger_total(case) == Decimal("250.00")
    assert Decimal(_summary(case, "month", "2026-09-11")["total"]) == Decimal("250.00")
    report = _report(case)
    assert report["installed_doors"] == 1
    assert Decimal(report["actual_payroll_total"]) == Decimal("250.00")
    assert Decimal(report["actual_revenue_total"]) == Decimal("1000.00")


def test_addon_snapshot_and_correction_survive_door_cancellation(payroll_case):
    case = payroll_case
    response = case.client.post("/api/v1/admin/addons/types", headers=case.owner, json={
        "name": "Additional sealing", "unit": "pcs",
        "default_client_price": "160.00", "default_installer_price": "80.00",
    })
    assert response.status_code == 200, response.text
    addon_type_id = response.json()["id"]
    plan = {
        "addon_type_id": addon_type_id, "qty_planned": "2.00",
        "client_price": "160.00", "installer_price": "80.00",
    }
    plan_path = f"/api/v1/admin/addons/projects/{case.project_id}/plan"
    assert case.client.put(plan_path, headers=case.owner, json=plan).status_code == 200
    fact = {
        "addon_type_id": addon_type_id, "qty_done": "2.00",
        "client_event_id": "payroll-addon", "done_at": INSTALLED_AT.isoformat(),
    }
    fact_path = f"/api/v1/installer/addons/projects/{case.project_id}/facts"
    for expected in (True, False):
        response = case.client.post(fact_path, headers=case.installer, json=fact)
        assert response.status_code == 200, response.text
        assert response.json()["applied"] is expected
    addon_work = case.session.query(CompletedWorkORM).filter(
        CompletedWorkORM.company_id == case.company_id, CompletedWorkORM.work_kind == "ADDON",
    ).one()
    addon_id = addon_work.id
    assert addon_work.amount_snapshot == Decimal("160.00")

    plan["installer_price"] = "100.00"
    assert case.client.put(plan_path, headers=case.owner, json=plan).status_code == 200
    case.session.expire_all()
    assert addon_work.amount_snapshot == Decimal("160.00")
    forbidden = case.client.post("/api/v1/admin/earnings/corrections", headers=case.installer, json={
        "completed_work_id": str(addon_id), "rate_snapshot": "90.00", "reason": "Not authorized",
    })
    assert forbidden.status_code == 403
    _correct(case, entry_id=addon_id, rate="90.00")
    duplicate = case.client.post("/api/v1/admin/earnings/corrections", headers=case.owner, json={
        "completed_work_id": str(addon_id), "rate_snapshot": "90.00", "reason": "Repeated request",
    })
    assert duplicate.status_code == 409
    _correct(case)
    _cancel(case)
    assert _ledger_total(case) == Decimal("180.00")
    assert Decimal(_summary(case, "month", "2026-09-11")["total"]) == Decimal("180.00")
    report = _report(case)
    assert Decimal(report["actual_payroll_total"]) == Decimal("180.00")
    assert Decimal(report["actual_revenue_total"]) == Decimal("320.00")
    with patch("app.modules.doors.application.use_cases.utcnow", return_value=CANCELLED_AT):
        response = case.client.post(f"/api/v1/installer/doors/{case.door_id}/install", headers=case.installer)
    assert response.status_code == 200, response.text
    assert _ledger_total(case) == Decimal("430.00")
    report = _report(case)
    assert Decimal(report["actual_payroll_total"]) == Decimal("430.00")
    assert Decimal(report["actual_revenue_total"]) == Decimal("1320.00")
    assert Decimal(report["actual_profit_total"]) == Decimal("890.00")


@pytest.mark.parametrize("first", ["cancel", "correct"])
def test_cancellation_and_correction_lock_company_before_door(payroll_case, monkeypatch, first):
    case = payroll_case
    waiting = threading.Event()
    main_thread = threading.get_ident()
    lock_company = FactoryPriceListsRepository.lock_company

    def observe_lock(self, company_id):
        if threading.get_ident() != main_thread:
            waiting.set()
        return lock_company(self, company_id)

    monkeypatch.setattr(FactoryPriceListsRepository, "lock_company", observe_lock)

    def apply(uow, operation):
        if operation == "correct":
            EarningsAdminApiService.create_correction(
                uow, company_id=case.company_id, actor_user_id=case.owner_id,
                completed_work_id=case.original_id, rate_snapshot=Decimal("300.00"), reason="Test correction",
            )
        else:
            DoorUseCases.admin_override(uow, AdminOverrideDoor(
                company_id=case.company_id, actor_user_id=case.owner_id, door_id=case.door_id,
                new_status="NOT_INSTALLED", reason_id=case.reason_id, override_reason="Test cancellation",
            ), actor_role="ADMIN")

    def second():
        try:
            with SqlAlchemyUnitOfWork() as uow:
                uow.session.execute(text("SET LOCAL lock_timeout = '15s'"))
                apply(uow, "correct" if first == "cancel" else "cancel")
        except Conflict:
            return "conflict"
        return "applied"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with SqlAlchemyUnitOfWork() as uow:
            assert uow.price_lists.lock_company(case.company_id)
            uow.doors.get(company_id=case.company_id, door_id=case.door_id, for_update=True)
            attempt = executor.submit(second)
            assert waiting.wait(timeout=15), "The concurrent operation must first attempt the company lock"
            apply(uow, first)
        assert attempt.result(timeout=30) == ("conflict" if first == "cancel" else "applied")
    case.session.expire_all()
    assert _ledger_total(case) == Decimal("0.00")
    assert case.session.get(DoorORM, case.door_id).status == DoorStatus.NOT_INSTALLED
