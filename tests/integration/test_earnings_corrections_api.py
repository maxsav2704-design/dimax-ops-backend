from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.modules.addons.domain.enums import AddonFactSource
from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.application.installer_api_service import InstallerEarningsApiService
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


class _SessionUow:
    def __init__(self, session) -> None:
        self.session = session


def _login(client_raw, *, company_id: str, email: str, password: str) -> str:
    resp = client_raw.post(
        "/api/v1/auth/login",
        json={
            "company_id": company_id,
            "email": email,
            "password": password,
            "device_id": f"earnings-correction-{email}",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _make_project(*, company_id: uuid.UUID, name: str) -> ProjectORM:
    return ProjectORM(
        company_id=company_id,
        name=name,
        code=f"PRJ-{uuid.uuid4().hex[:6].upper()}",
        address=f"{name} address",
        status=ProjectStatus.OK,
        lifecycle_status="ACTIVE",
        health_status="NORMAL",
    )


def _make_door(
    *,
    company_id: uuid.UUID,
    project_id: uuid.UUID,
    door_type_id: uuid.UUID,
    installer_id: uuid.UUID,
    unit_label: str,
) -> DoorORM:
    return DoorORM(
        company_id=company_id,
        project_id=project_id,
        door_type_id=door_type_id,
        unit_label=unit_label,
        door_code=f"{unit_label}-{uuid.uuid4().hex[:4]}",
        our_price=Decimal("100.00"),
        installer_rate_snapshot=Decimal("50.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer_id,
        installed_at=datetime.now(timezone.utc),
        is_locked=True,
        is_critical=False,
        version=1,
        surcharge_pct=Decimal("100.00"),
    )


def _seed_original_completed_work(
    *,
    db_session,
    company_id: uuid.UUID,
    make_door_type,
    installer_name: str = "Correction Installer",
    unit_label: str = "CW-01",
    amount: Decimal = Decimal("40.00"),
) -> tuple[InstallerORM, CompletedWorkORM]:
    installer = InstallerORM(
        company_id=company_id,
        full_name=installer_name,
        phone=f"+1555{uuid.uuid4().hex[:8]}",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=None,
    )
    project = _make_project(company_id=company_id, name=f"Correction {unit_label}")
    door_type = make_door_type(name=f"Correction Door {unit_label}")
    db_session.add_all([installer, project])
    db_session.flush()

    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        installer_id=installer.id,
        unit_label=unit_label,
    )
    db_session.add(door)
    db_session.flush()

    original = CompletedWorkORM(
        company_id=company_id,
        project_id=project.id,
        door_id=door.id,
        installer_id=installer.id,
        completed_at=datetime.now(timezone.utc),
        quantity=Decimal("1.00"),
        rate_snapshot=amount,
        amount_snapshot=amount,
        entry_type="ORIGINAL",
        correction_ref_id=None,
        reason=None,
    )
    db_session.add(original)
    db_session.commit()
    db_session.refresh(installer)
    db_session.refresh(original)
    return installer, original


def _seed_cross_company_completed_work(
    *,
    db_session,
    original: CompletedWorkORM,
    amount: Decimal = Decimal("999.00"),
) -> CompletedWorkORM:
    row = CompletedWorkORM(
        company_id=uuid.uuid4(),
        project_id=original.project_id,
        door_id=original.door_id,
        installer_id=original.installer_id,
        completed_at=datetime(2026, 5, 8, 8, 0, tzinfo=timezone.utc),
        quantity=Decimal("1.00"),
        rate_snapshot=amount,
        amount_snapshot=amount,
        entry_type="ORIGINAL",
        correction_ref_id=None,
        reason="Foreign company payroll row",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _seed_addon_completed_work(
    *,
    db_session,
    company_id: uuid.UUID,
    installer_name: str = "Addon Correction Installer",
) -> tuple[InstallerORM, CompletedWorkORM, ProjectAddonFactORM]:
    installer = InstallerORM(
        company_id=company_id,
        full_name=installer_name,
        phone=f"+1555{uuid.uuid4().hex[:8]}",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=None,
    )
    project = _make_project(company_id=company_id, name="Addon Correction")
    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Frame foam",
        unit="pcs",
        default_client_price=Decimal("20.00"),
        default_installer_price=Decimal("12.00"),
        is_active=True,
        deleted_at=None,
    )
    db_session.add_all([installer, project, addon_type])
    db_session.flush()

    fact = ProjectAddonFactORM(
        company_id=company_id,
        project_id=project.id,
        installer_id=installer.id,
        addon_type_id=addon_type.id,
        qty_done=Decimal("2.00"),
        done_at=datetime.now(timezone.utc),
        comment="Offline addon",
        source=AddonFactSource.OFFLINE,
        client_event_id=f"addon-correction-{uuid.uuid4()}",
    )
    db_session.add(fact)
    db_session.flush()

    original = CompletedWorkORM(
        company_id=company_id,
        project_id=project.id,
        door_id=None,
        addon_fact_id=fact.id,
        installer_id=installer.id,
        completed_at=fact.done_at,
        quantity=Decimal("2.00"),
        rate_snapshot=Decimal("12.00"),
        amount_snapshot=Decimal("24.00"),
        work_kind="ADDON",
        entry_type="ORIGINAL",
        correction_ref_id=None,
        reason="Additional work",
    )
    db_session.add(original)
    db_session.commit()
    db_session.refresh(installer)
    db_session.refresh(original)
    db_session.refresh(fact)
    return installer, original, fact


def test_admin_earnings_correction_creates_reversal_and_correction_rows(
    client,
    db_session,
    company_id,
    make_door_type,
):
    _installer, original = _seed_original_completed_work(
        db_session=db_session,
        company_id=company_id,
        make_door_type=make_door_type,
    )

    resp = client.post(
        "/api/v1/admin/earnings/corrections",
        json={
            "completed_work_id": str(original.id),
            "rate_snapshot": "55.00",
            "reason": "Adjusted after finance review",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["original"]["id"] == str(original.id)
    assert body["reversal"]["entry_type"] == "REVERSAL"
    assert body["reversal"]["correction_ref_id"] == str(original.id)
    assert body["reversal"]["amount_snapshot"] == "-40.00"
    assert body["correction"]["entry_type"] == "CORRECTION"
    assert body["correction"]["correction_ref_id"] == str(original.id)
    assert body["correction"]["rate_snapshot"] == "55.00"
    assert body["correction"]["amount_snapshot"] == "55.00"

    db_session.expire_all()
    audit = (
        db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type == "completed_work",
            AuditLogORM.entity_id == original.id,
            AuditLogORM.action == "EARNINGS_CORRECTION",
        )
        .one()
    )
    assert audit.reason == "Adjusted after finance review"
    assert audit.before["original"]["amount_snapshot"] == "40.00"
    assert audit.after["correction"]["amount_snapshot"] == "55.00"
    assert audit.after["reversal"]["amount_snapshot"] == "-40.00"

    rows = (
        db_session.query(CompletedWorkORM)
        .filter(CompletedWorkORM.correction_ref_id == original.id)
        .order_by(CompletedWorkORM.entry_type.asc())
        .all()
    )
    assert [row.entry_type for row in rows] == ["CORRECTION", "REVERSAL"]
    assert Decimal(str(rows[0].amount_snapshot)) == Decimal("55.00")
    assert Decimal(str(rows[1].amount_snapshot)) == Decimal("-40.00")


def test_admin_earnings_correction_allows_addon_fact_reversal_and_correction(
    client,
    db_session,
    company_id,
):
    installer, original, fact = _seed_addon_completed_work(
        db_session=db_session,
        company_id=company_id,
    )

    resp = client.post(
        "/api/v1/admin/earnings/corrections",
        json={
            "completed_work_id": str(original.id),
            "rate_snapshot": "14.00",
            "reason": "Adjusted add-on unit price",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["reversal"]["amount_snapshot"] == "-24.00"
    assert body["correction"]["amount_snapshot"] == "28.00"

    ledger_resp = client.get(
        f"/api/v1/admin/earnings/ledger?installer_id={installer.id}&work_kind=ADDON"
    )
    assert ledger_resp.status_code == 200, ledger_resp.text
    rows = ledger_resp.json()["items"]
    assert len(rows) == 3
    assert {row["entry_type"] for row in rows} == {
        "ORIGINAL",
        "REVERSAL",
        "CORRECTION",
    }
    assert {row["addon_fact_id"] for row in rows} == {str(fact.id)}
    assert {row["addon_type_id"] for row in rows} == {str(fact.addon_type_id)}
    assert {row["addon_type_name"] for row in rows} == {"Frame foam"}
    assert {row["addon_comment"] for row in rows} == {"Offline addon"}

    summary = InstallerEarningsApiService.summary(
        _SessionUow(db_session),
        company_id=company_id,
        installer_id=installer.id,
        period="day",
        anchor_date=fact.done_at.date(),
    )
    assert summary.total == Decimal("28.00")


def test_admin_earnings_correction_rejects_non_positive_rate(
    client,
    db_session,
    company_id,
    make_door_type,
):
    _installer, original = _seed_original_completed_work(
        db_session=db_session,
        company_id=company_id,
        make_door_type=make_door_type,
        unit_label="NON-POSITIVE-RATE",
    )

    for rate in ("0.00", "-1.00", "1.001"):
        resp = client.post(
            "/api/v1/admin/earnings/corrections",
            json={
                "completed_work_id": str(original.id),
                "rate_snapshot": rate,
                "reason": "Invalid payroll correction",
            },
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
        assert resp.json()["error"]["field"] == "rate_snapshot"

    rows = (
        db_session.query(CompletedWorkORM)
        .filter(CompletedWorkORM.correction_ref_id == original.id)
        .all()
    )
    assert rows == []


def test_admin_earnings_ledger_lists_entries_needed_for_corrections(
    client,
    db_session,
    company_id,
    make_door_type,
):
    installer, original = _seed_original_completed_work(
        db_session=db_session,
        company_id=company_id,
        make_door_type=make_door_type,
        unit_label="LEDGER-01",
    )

    before_resp = client.get(
        f"/api/v1/admin/earnings/ledger?installer_id={installer.id}&entry_type=ORIGINAL"
    )
    assert before_resp.status_code == 200, before_resp.text
    before_body = before_resp.json()
    assert before_body["total"] == 1
    assert before_body["items"][0]["id"] == str(original.id)
    assert before_body["items"][0]["can_correct"] is True
    assert before_body["items"][0]["door_label"] == "LEDGER-01"
    assert before_body["items"][0]["installer_name"] == "Correction Installer"

    correction_resp = client.post(
        "/api/v1/admin/earnings/corrections",
        json={
            "completed_work_id": str(original.id),
            "rate_snapshot": "55.00",
            "reason": "Ledger visible correction",
        },
    )
    assert correction_resp.status_code == 201, correction_resp.text

    ledger_resp = client.get(
        f"/api/v1/admin/earnings/ledger?installer_id={installer.id}&project_id={original.project_id}"
    )
    assert ledger_resp.status_code == 200, ledger_resp.text
    body = ledger_resp.json()
    assert body["total"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0

    by_type = {item["entry_type"]: item for item in body["items"]}
    assert by_type["ORIGINAL"]["id"] == str(original.id)
    assert by_type["ORIGINAL"]["can_correct"] is False
    assert by_type["ORIGINAL"]["work_kind"] == "DOOR"
    assert by_type["ORIGINAL"]["project_name"] == "Correction LEDGER-01"
    assert by_type["ORIGINAL"]["door_label"] == "LEDGER-01"
    assert by_type["REVERSAL"]["correction_ref_id"] == str(original.id)
    assert by_type["REVERSAL"]["amount_snapshot"] == "-40.00"
    assert by_type["REVERSAL"]["can_correct"] is False
    assert by_type["CORRECTION"]["correction_ref_id"] == str(original.id)
    assert by_type["CORRECTION"]["amount_snapshot"] == "55.00"
    assert by_type["CORRECTION"]["can_correct"] is False


def test_admin_earnings_ledger_export_csv_matches_filters(
    client,
    db_session,
    company_id,
    make_door_type,
):
    installer, original = _seed_original_completed_work(
        db_session=db_session,
        company_id=company_id,
        make_door_type=make_door_type,
        installer_name="Export Installer",
        unit_label="EXPORT-01",
        amount=Decimal("70.00"),
    )
    _other_installer, other_original = _seed_original_completed_work(
        db_session=db_session,
        company_id=company_id,
        make_door_type=make_door_type,
        installer_name="Other Export Installer",
        unit_label="EXPORT-OTHER",
        amount=Decimal("90.00"),
    )
    original.completed_at = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    original_door = db_session.get(DoorORM, original.door_id)
    assert original_door is not None
    outside_door = _make_door(
        company_id=company_id,
        project_id=original.project_id,
        door_type_id=original_door.door_type_id,
        installer_id=installer.id,
        unit_label="EXPORT-OUTSIDE",
    )
    outside_door.installed_at = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    db_session.add(outside_door)
    db_session.flush()
    outside_period = CompletedWorkORM(
        company_id=company_id,
        project_id=original.project_id,
        door_id=outside_door.id,
        installer_id=installer.id,
        completed_at=outside_door.installed_at,
        quantity=Decimal("1.00"),
        rate_snapshot=Decimal("33.00"),
        amount_snapshot=Decimal("33.00"),
        work_kind="DOOR",
        entry_type="ORIGINAL",
        correction_ref_id=None,
        reason="Outside payroll period",
    )
    db_session.add(outside_period)
    db_session.commit()

    resp = client.get(
        "/api/v1/admin/earnings/ledger/export"
        f"?installer_id={installer.id}&project_id={original.project_id}"
        "&date_from=2026-05-01T00:00:00Z&date_to=2026-06-01T00:00:00Z"
        "&limit=100"
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment;" in resp.headers["content-disposition"]
    csv_body = resp.text
    assert (
        "id,completed_at,entry_type,work_kind,installer_id,installer_name,project_id,"
        "project_name,door_id,door_label,door_code,addon_fact_id,addon_type_id,"
        "addon_type_name,addon_comment,quantity,"
        "rate_snapshot,amount_snapshot,correction_ref_id,can_correct,reason"
    ) in csv_body
    assert str(original.id) in csv_body
    assert "Export Installer" in csv_body
    assert "Correction EXPORT-01" in csv_body
    assert "EXPORT-01" in csv_body
    assert "70.00" in csv_body
    assert str(other_original.id) not in csv_body
    assert "Other Export Installer" not in csv_body
    assert str(outside_period.id) not in csv_body
    assert "Outside payroll period" not in csv_body


def test_admin_earnings_ledger_does_not_leak_foreign_company_rows(
    client,
    db_session,
    company_id,
    make_door_type,
):
    installer, original = _seed_original_completed_work(
        db_session=db_session,
        company_id=company_id,
        make_door_type=make_door_type,
        installer_name="Tenant Safe Installer",
        unit_label="TENANT-LEDGER",
        amount=Decimal("80.00"),
    )
    foreign_row = _seed_cross_company_completed_work(
        db_session=db_session,
        original=original,
        amount=Decimal("999.00"),
    )
    foreign_row_id = foreign_row.id

    try:
        ledger_resp = client.get(
            f"/api/v1/admin/earnings/ledger?installer_id={installer.id}&limit=100"
        )
        assert ledger_resp.status_code == 200, ledger_resp.text
        ledger_body = ledger_resp.json()
        ids = {item["id"] for item in ledger_body["items"]}
        assert str(original.id) in ids
        assert str(foreign_row_id) not in ids
        assert all(item["amount_snapshot"] != "999.00" for item in ledger_body["items"])

        export_resp = client.get(
            f"/api/v1/admin/earnings/ledger/export?installer_id={installer.id}&limit=100"
        )
        assert export_resp.status_code == 200, export_resp.text
        assert str(original.id) in export_resp.text
        assert str(foreign_row_id) not in export_resp.text
        assert "999.00" not in export_resp.text
        assert "Foreign company payroll row" not in export_resp.text
    finally:
        db_session.rollback()
        db_session.query(CompletedWorkORM).filter(
            CompletedWorkORM.id == foreign_row_id
        ).delete(synchronize_session=False)
        db_session.commit()


def test_admin_earnings_correction_rejects_foreign_company_original(
    client,
    db_session,
    company_id,
    make_door_type,
):
    _installer, original = _seed_original_completed_work(
        db_session=db_session,
        company_id=company_id,
        make_door_type=make_door_type,
        unit_label="TENANT-CORRECTION",
        amount=Decimal("85.00"),
    )
    foreign_row = _seed_cross_company_completed_work(
        db_session=db_session,
        original=original,
        amount=Decimal("777.00"),
    )
    foreign_row_id = foreign_row.id

    try:
        resp = client.post(
            "/api/v1/admin/earnings/corrections",
            json={
                "completed_work_id": str(foreign_row_id),
                "rate_snapshot": "100.00",
                "reason": "Cross company correction attempt",
            },
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"

        leaked_corrections = (
            db_session.query(CompletedWorkORM)
            .filter(CompletedWorkORM.correction_ref_id == foreign_row_id)
            .all()
        )
        assert leaked_corrections == []
        leaked_audits = (
            db_session.query(AuditLogORM)
            .filter(
                AuditLogORM.entity_type == "completed_work",
                AuditLogORM.entity_id == foreign_row_id,
                AuditLogORM.action == "EARNINGS_CORRECTION",
            )
            .all()
        )
        assert leaked_audits == []
    finally:
        db_session.rollback()
        db_session.query(CompletedWorkORM).filter(
            CompletedWorkORM.correction_ref_id == foreign_row_id
        ).delete(synchronize_session=False)
        db_session.query(CompletedWorkORM).filter(
            CompletedWorkORM.id == foreign_row_id
        ).delete(synchronize_session=False)
        db_session.commit()


def test_admin_earnings_correction_rejects_missing_original(
    client,
):
    missing_id = uuid.uuid4()
    resp = client.post(
        "/api/v1/admin/earnings/corrections",
        json={
            "completed_work_id": str(missing_id),
            "rate_snapshot": "55.00",
            "reason": "Missing original",
        },
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_admin_earnings_correction_requires_rate_capability(
    client_raw,
    db_session,
    company_id,
    make_user,
):
    password = "EarningsNoRates123"  # gitleaks:allow - deterministic test credential
    user = make_user(role=UserRole.ADMIN, password=password, with_admin_profile=False)
    db_session.add(
        AdminProfileORM(
            company_id=company_id,
            user_id=user.id,
            admin_scope="OPERATIONS",
            can_view_rates=False,
            can_manage_imports=True,
            can_manage_users=True,
        )
    )
    db_session.commit()

    token = _login(
        client_raw,
        company_id=str(company_id),
        email=user.email,
        password=password,
    )
    resp = client_raw.post(
        "/api/v1/admin/earnings/corrections",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "completed_work_id": str(uuid.uuid4()),
            "rate_snapshot": "55.00",
            "reason": "No financial scope",
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_admin_earnings_ledger_requires_rate_capability(
    client_raw,
    db_session,
    company_id,
    make_user,
):
    password = "EarningsLedgerNoRates123"  # gitleaks:allow - deterministic test credential
    user = make_user(role=UserRole.ADMIN, password=password, with_admin_profile=False)
    db_session.add(
        AdminProfileORM(
            company_id=company_id,
            user_id=user.id,
            admin_scope="OPERATIONS",
            can_view_rates=False,
            can_manage_imports=True,
            can_manage_users=True,
        )
    )
    db_session.commit()

    token = _login(
        client_raw,
        company_id=str(company_id),
        email=user.email,
        password=password,
    )
    for path in (
        "/api/v1/admin/earnings/ledger",
        "/api/v1/admin/earnings/ledger/export",
    ):
        resp = client_raw.get(
            path,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize(
    ("existing_entry_type", "rate_snapshot", "amount_snapshot"),
    [
        ("REVERSAL", Decimal("-40.00"), Decimal("-40.00")),
        ("CORRECTION", Decimal("50.00"), Decimal("50.00")),
    ],
)
def test_admin_earnings_correction_rejects_existing_correction_entry(
    client,
    db_session,
    company_id,
    make_door_type,
    existing_entry_type,
    rate_snapshot,
    amount_snapshot,
):
    _installer, original = _seed_original_completed_work(
        db_session=db_session,
        company_id=company_id,
        make_door_type=make_door_type,
        unit_label="CW-02",
    )
    db_session.add(
        CompletedWorkORM(
            company_id=company_id,
            project_id=original.project_id,
            door_id=original.door_id,
            installer_id=original.installer_id,
            completed_at=original.completed_at,
            quantity=Decimal("1.00"),
            rate_snapshot=rate_snapshot,
            amount_snapshot=amount_snapshot,
            entry_type=existing_entry_type,
            correction_ref_id=original.id,
            reason="Existing correction entry",
        )
    )
    db_session.commit()

    resp = client.post(
        "/api/v1/admin/earnings/corrections",
        json={
            "completed_work_id": str(original.id),
            "rate_snapshot": "60.00",
            "reason": "Second correction attempt",
        },
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "CONFLICT"


def test_earnings_summary_reflects_admin_correction_write_path(
    client,
    db_session,
    company_id,
    make_door_type,
):
    installer, original = _seed_original_completed_work(
        db_session=db_session,
        company_id=company_id,
        make_door_type=make_door_type,
        unit_label="CW-03",
    )

    resp = client.post(
        "/api/v1/admin/earnings/corrections",
        json={
            "completed_work_id": str(original.id),
            "rate_snapshot": "55.00",
            "reason": "Installer payout corrected",
        },
    )
    assert resp.status_code == 201, resp.text

    summary = InstallerEarningsApiService.summary(
        _SessionUow(db_session),
        company_id=company_id,
        installer_id=installer.id,
        period="day",
        anchor_date=original.completed_at.date(),
    )
    assert summary.total == Decimal("55.00")
    assert summary.jobs_count == 1
