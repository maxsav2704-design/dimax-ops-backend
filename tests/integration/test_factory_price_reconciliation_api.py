from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM, ProjectAddonPlanORM, ProjectUrgencySurchargeORM
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.models import InstallerRateORM


URL = "/api/v1/admin/price-lists"


@pytest.fixture()
def inventory(client, db_session, company_id, make_door_type, make_installer):
    door_type = make_door_type(name="Entrance")
    missing_type = make_door_type(name="Unpriced door")
    one = make_installer(full_name="Installer One")
    two = make_installer(full_name="Installer Two")
    inactive = make_installer(full_name="Inactive installer", is_active=False)
    addon = AddonTypeORM(company_id=company_id, name="Adjustment", unit="pcs", default_installer_price=Decimal("9"))
    first = ProjectORM(company_id=company_id, name="First object", address="QA", status="OK")
    second = ProjectORM(company_id=company_id, name="Second object", address="QA", status="OK")
    db_session.add_all([addon, first, second])
    db_session.flush()
    now = datetime.now(timezone.utc)
    rate_rows = [InstallerRateORM(company_id=company_id, installer_id=person.id, door_type_id=door_type.id,
        price=Decimal(price), effective_from=now + timedelta(days=days)) for person, price, days in (
            (one, "100", -60), (one, "125", -30), (two, "250", -30), (two, "300", 30), (inactive, "200", -30))]
    snapshot = DoorORM(company_id=company_id, project_id=first.id, door_type_id=door_type.id,
        installer_id=one.id, unit_label="A-101", our_price=Decimal("500"), installer_rate_snapshot=Decimal("100"),
        apply_surcharge_to_installer=True, surcharge_pct=Decimal("125"))
    fallback = DoorORM(company_id=company_id, project_id=second.id, door_type_id=door_type.id,
        installer_id=two.id, unit_label="B-101", our_price=Decimal("500"), surcharge_pct=Decimal("200"))
    installed = DoorORM(company_id=company_id, project_id=first.id, door_type_id=door_type.id,
        installer_id=one.id, unit_label="A-102", our_price=Decimal("500"), installer_rate_snapshot=Decimal("777"),
        status="INSTALLED", is_locked=True)
    plans = [ProjectAddonPlanORM(company_id=company_id, project_id=project.id, addon_type_id=addon.id,
        qty_planned=Decimal("10"), installer_price=Decimal(price), client_price=Decimal("20"))
        for project, price in ((first, "9"), (second, "12"))]
    unpaid = ProjectAddonFactORM(company_id=company_id, project_id=first.id, installer_id=one.id,
        addon_type_id=addon.id, qty_done=Decimal("1.50"), done_at=now - timedelta(days=1))
    db_session.add_all([*rate_rows, snapshot, fallback, installed, *plans, unpaid])
    db_session.flush()
    historical = CompletedWorkORM(company_id=company_id, project_id=first.id, door_id=installed.id,
        installer_id=one.id, completed_at=now, quantity=Decimal("1"), rate_snapshot=Decimal("777"), amount_snapshot=Decimal("777"))
    urgency = ProjectUrgencySurchargeORM(company_id=company_id, project_id=first.id, scope="PROJECT",
        reason="Existing urgency agreement", client_amount=Decimal("50"), installer_amount=Decimal("25"))
    db_session.add_all([historical, urgency])
    db_session.commit()
    response = client.post(URL, json={"request_id": str(uuid4()), "expected_latest_version": 0,
        "reason": "Common factory offer", "agreement_reference": "QA agreement",
        "items": [{"kind": "DOOR", "target_id": str(door_type.id), "installer_price": "250.00"},
                  {"kind": "ADDON", "target_id": str(addon.id), "installer_price": "9.00"}]})
    assert response.status_code == 200, response.text
    return {"path": f'{URL}/{response.json()["id"]}/reconciliation', "list": response.json(),
        "type": door_type, "addon": addon, "missing_type": missing_type, "one": one, "two": two,
        "first": first, "second": second, "snapshot": snapshot, "fallback": fallback,
        "installed": installed, "historical": historical, "plans": plans, "unpaid": unpaid}


def report(client, inventory, **params):
    response = client.get(inventory["path"], params={"limit": 100, **params})
    assert response.status_code == 200, response.text
    return response.json()


def line(data, source, source_id):
    return next(row for row in data["items"] if row["source_type"] == source and row["source_id"] == str(source_id))


def test_effective_rates_snapshots_surcharges_and_history(client, inventory):
    data = report(client, inventory)
    assert data["version"] == 1 and data["currency"] == "ILS" and data["generated_at"]
    rates = [row for row in data["items"] if row["source_type"] == "INSTALLER_RATE"]
    assert sorted(row["legacy_price"] for row in rates) == ["125.00", "200.00", "250.00"]
    assert next(row for row in rates if row["installer_id"] == str(inventory["one"].id))["status"] == "DIFFERENT"
    future = next(row for row in data["items"] if row["source_type"] == "SCHEDULED_RATE")
    assert future["legacy_price"] == "300.00" and future["review_required"]
    snapshot = line(data, "DOOR", inventory["snapshot"].id)
    assert snapshot["legacy_price"] == "125.00" and snapshot["delta"] == "125.00"
    assert snapshot["uses_snapshot"] and snapshot["uses_surcharge"] and snapshot["review_required"]
    fallback = line(data, "DOOR", inventory["fallback"].id)
    assert fallback["legacy_price"] == "250.00" and fallback["status"] == "MATCH"
    assert fallback["legacy_variants"] == 2 and fallback["review_required"]
    assert not fallback["uses_snapshot"] and not fallback["uses_surcharge"]
    assert not any(row["source_id"] == str(inventory["installed"].id) for row in data["items"])
    summary = data["summary"]
    assert summary["historical_entries"] == summary["door_snapshots"] == summary["door_surcharges"] == 1
    assert summary["scheduled_rates"] == summary["urgency_surcharges"] == summary["pending_addon_facts"] == 1
    assert data["total"] == summary["total_sources"] == 11
    assert summary["multiple_rate_types"] == 2


def test_project_prices_defaults_and_unpaid_work_are_distinct(client, inventory):
    data = report(client, inventory)
    first = line(data, "ADDON_PLAN", inventory["plans"][0].id)
    second = line(data, "ADDON_PLAN", inventory["plans"][1].id)
    assert first["legacy_price"] == "9.00" and first["status"] == "MATCH"
    assert second["legacy_price"] == "12.00" and second["delta"] == "-3.00"
    assert second["project_name"] == "Second object"
    default = line(data, "ADDON_DEFAULT", inventory["addon"].id)
    assert default["project_id"] is None and default["legacy_price"] == "9.00"
    unpaid = line(data, "ADDON_FACT", inventory["unpaid"].id)
    assert unpaid["quantity"] == "1.50" and unpaid["status"] == "MATCH" and unpaid["review_required"]
    missing = line(data, "CATALOG", inventory["missing_type"].id)
    assert missing["status"] == "MISSING_PROPOSED" and missing["proposed_price"] is None


def test_pagination_and_filters_preserve_global_summary(client, inventory):
    all_rows = report(client, inventory)
    pages = [report(client, inventory, limit=3, offset=offset) for offset in range(0, all_rows["total"], 3)]
    assert [row for page in pages for row in page["items"]] == all_rows["items"]
    assert all(page["summary"] == all_rows["summary"] for page in pages)
    selected = report(client, inventory, issues_only=True, kind="ADDON")
    assert selected["total"] == 3 and all(row["kind"] == "ADDON" and row["review_required"] for row in selected["items"])
    assert selected["summary"] == all_rows["summary"]
    empty_page = report(client, inventory, offset=1000)
    assert empty_page["items"] == [] and empty_page["total"] == all_rows["total"]
    assert empty_page["summary"] == all_rows["summary"]


def test_catalog_unit_changes_are_not_compared_as_money(client, inventory, db_session):
    inventory["addon"].name = "Renamed adjustment"
    inventory["addon"].unit = "hour"
    db_session.commit()
    data = report(client, inventory)
    rows = [row for row in data["items"] if row["kind"] == "ADDON"]
    assert all(row["status"] == "UNIT_CHANGED" and row["delta"] is None and row["review_required"] for row in rows)
    assert all(row["name"] == "Renamed adjustment" and row["proposed_name"] == "Adjustment" for row in rows)
    assert all(row["unit"] == "hour" and row["proposed_unit"] == "pcs" for row in rows)
    assert data["summary"]["unit_changed"] == 4


def test_matching_renamed_catalog_still_requires_review(client, inventory, db_session):
    inventory["addon"].name = "Renamed adjustment"
    db_session.commit()
    data = report(client, inventory, issues_only=True)
    default = line(data, "ADDON_DEFAULT", inventory["addon"].id)
    assert default["status"] == "MATCH" and default["catalog_changed"] and default["review_required"]


def test_missing_rate_and_zero_plan_remain_visible(client, inventory, db_session):
    inventory["plans"][0].installer_price = Decimal("0")
    db_session.execute(text("DELETE FROM installer_rates WHERE company_id=:cid AND installer_id=:iid"),
                       {"cid": inventory["two"].company_id, "iid": inventory["two"].id})
    db_session.commit()
    data = report(client, inventory)
    assert line(data, "ADDON_PLAN", inventory["plans"][0].id)["status"] == "MISSING_LEGACY"
    assert line(data, "ADDON_FACT", inventory["unpaid"].id)["status"] == "MISSING_LEGACY"
    assert line(data, "DOOR", inventory["fallback"].id)["status"] == "MISSING_LEGACY"


def test_unplanned_work_remains_visible_but_accrued_facts_stay_in_history(client, inventory, db_session, company_id):
    db_session.delete(inventory["plans"][0])
    db_session.commit()
    data = report(client, inventory)
    unpaid = line(data, "ADDON_FACT", inventory["unpaid"].id)
    assert unpaid["status"] == "MISSING_LEGACY" and unpaid["legacy_price"] is None
    fact = inventory["unpaid"]
    db_session.add(CompletedWorkORM(company_id=company_id, project_id=fact.project_id, addon_fact_id=fact.id,
        installer_id=fact.installer_id, completed_at=fact.done_at, quantity=fact.qty_done,
        rate_snapshot=Decimal("9"), amount_snapshot=Decimal("13.50"), work_kind="ADDON", entry_type="ORIGINAL"))
    db_session.commit()
    data = report(client, inventory)
    assert not any(row["source_type"] == "ADDON_FACT" for row in data["items"])
    assert data["summary"]["pending_addon_facts"] == 0 and data["summary"]["historical_entries"] == 2


@pytest.mark.parametrize("snapshot,surcharge,expected", [("100", "100", "100.00"), ("100.05", "110", "110.06")])
def test_door_projection_matches_existing_completion_rounding(client, inventory, db_session, snapshot, surcharge, expected):
    door = inventory["snapshot"]
    door.installer_rate_snapshot = Decimal(snapshot)
    door.surcharge_pct = Decimal(surcharge)
    db_session.commit()
    assert line(report(client, inventory), "DOOR", door.id)["legacy_price"] == expected


def test_reading_and_cancelled_version_never_modify_business_data(client_admin_real_uow, inventory, db_session, company_id):
    tables = ("installer_rates", "doors", "project_addon_plans", "project_addon_facts", "completed_work",
              "sync_change_log", "factory_price_lists", "factory_price_approvals", "audit_logs")
    def snapshot():
        return {table: db_session.execute(text(
            f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb) FROM {table} t WHERE company_id=:cid"
        ), {"cid": company_id}).scalar_one() for table in tables}
    before = snapshot()
    report(client_admin_real_uow, inventory)
    report(client_admin_real_uow, inventory, issues_only=True, offset=1000)
    assert client_admin_real_uow.get(f"{URL}/reconciliation").status_code == 200
    db_session.expire_all()
    assert snapshot() == before
    response = client_admin_real_uow.post(f'{URL}/{inventory["list"]["id"]}/cancel', json={"reason": "Factory amendment"})
    assert response.status_code == 200, response.text
    after_cancel = snapshot()
    report(client_admin_real_uow, inventory)
    db_session.expire_all()
    assert snapshot() == after_cancel


@pytest.mark.parametrize("scope,view_rates,expected", [
    ("OWNER", True, 200), ("OPERATIONS", True, 200), ("FINANCE", True, 200),
    ("VIEWER", True, 403), ("OPERATIONS", False, 403), ("FINANCE", False, 403), ("INSTALLER", False, 403),
])
def test_real_jwt_access(client_raw, inventory, make_user, db_session, company_id, scope, view_rates, expected):
    user = make_user(role=UserRole.INSTALLER if scope == "INSTALLER" else UserRole.ADMIN)
    if scope != "INSTALLER":
        profile = db_session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == user.id))
        profile.admin_scope = scope
        profile.can_view_rates = view_rates
        db_session.commit()
    response = client_raw.post("/api/v1/auth/login", json={"company_id": str(company_id), "email": user.email,
        "password": "secret123", "device_id": "price-reconciliation-tests"})
    assert response.status_code == 200, response.text
    headers = {"Authorization": f'Bearer {response.json()["access_token"]}'}
    response = client_raw.get(inventory["path"], headers=headers)
    assert response.status_code == expected, response.text
    response = client_raw.get(f"{URL}/reconciliation", headers=headers)
    assert response.status_code == expected, response.text


def test_foreign_price_list_and_tenant_references_do_not_leak_names(client, inventory, db_session, make_installer, make_door_type):
    assert client.get(f"{URL}/{uuid4()}/reconciliation").status_code == 404
    own_id = UUID(inventory["list"]["id"])
    own_company = inventory["one"].company_id
    foreign_installer = make_installer(full_name="FOREIGN PRIVATE NAME", company=uuid4())
    foreign_type = make_door_type(name="FOREIGN PRIVATE TYPE", company=uuid4())
    foreign_addon = AddonTypeORM(company_id=uuid4(), name="FOREIGN PRIVATE ADDON", unit="kg")
    db_session.add(foreign_addon)
    db_session.flush()
    malformed_plan = ProjectAddonPlanORM(company_id=own_company, project_id=inventory["first"].id,
        addon_type_id=foreign_addon.id, installer_price=Decimal("10"), client_price=Decimal("20"), qty_planned=Decimal("1"))
    db_session.add(malformed_plan)
    db_session.add(InstallerRateORM(company_id=own_company, installer_id=foreign_installer.id,
        door_type_id=foreign_type.id, price=Decimal("50"), effective_from=datetime.now(timezone.utc) - timedelta(days=1)))
    db_session.commit()
    try:
        response = client.get(inventory["path"])
        assert response.status_code == 200, response.text
        assert "FOREIGN PRIVATE" not in response.text
        assert any(row["status"] == "UNAVAILABLE" for row in response.json()["items"])
        malformed = line(response.json(), "ADDON_PLAN", malformed_plan.id)
        assert malformed["unit"] == "-" and malformed["status"] == "UNAVAILABLE"
        from app.modules.rates.application.reconciliation_service import FactoryPriceReconciliationService
        from app.shared.domain.errors import NotFound
        from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
        with SqlAlchemyUnitOfWork() as uow, pytest.raises(NotFound):
            FactoryPriceReconciliationService.get(uow, company_id=uuid4(), price_list_id=own_id,
                limit=20, offset=0, issues_only=False, kind=None)
    finally:
        # The intentionally malformed legacy references have no tenant-parent FK.
        db_session.rollback()
        db_session.execute(text("DELETE FROM installer_rates WHERE company_id=:cid AND installer_id=:iid"),
                           {"cid": own_company, "iid": foreign_installer.id})
        db_session.delete(foreign_installer)
        db_session.delete(foreign_type)
        db_session.delete(malformed_plan)
        db_session.delete(foreign_addon)
        db_session.commit()


def test_foreign_admin_cannot_read_known_version(client_raw, inventory, db_session, make_user):
    foreign_company = uuid4()
    db_session.add(CompanyORM(id=foreign_company, name="Other reconciliation company", is_active=True))
    db_session.commit()
    try:
        user = make_user(company=foreign_company, role=UserRole.ADMIN)
        login = client_raw.post("/api/v1/auth/login", json={"company_id": str(foreign_company), "email": user.email,
            "password": "secret123", "device_id": "foreign-reconciliation-test"})
        assert login.status_code == 200, login.text
        response = client_raw.get(inventory["path"], headers={"Authorization": f'Bearer {login.json()["access_token"]}'})
        assert response.status_code == 404, response.text
        response = client_raw.get(f"{URL}/reconciliation", headers={"Authorization": f'Bearer {login.json()["access_token"]}'})
        assert response.status_code == 200, response.text
        assert response.json()["items"] == [] and response.json()["summary"]["total_sources"] == 0
    finally:
        db_session.rollback()
        for table in ("audit_logs", "refresh_sessions", "admin_profiles", "users"):
            db_session.execute(text(f"DELETE FROM {table} WHERE company_id=:cid"), {"cid": foreign_company})
        db_session.execute(text("DELETE FROM companies WHERE id=:cid"), {"cid": foreign_company})
        db_session.commit()


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"kind": "OTHER"}])
def test_invalid_filters_are_rejected(client, inventory, params):
    assert client.get(inventory["path"], params=params).status_code == 422


def test_openapi_contract(client_raw):
    spec = client_raw.get("/openapi.json").json()
    for path in (URL + "/{price_list_id}/reconciliation", URL + "/reconciliation"):
        operation = spec["paths"][path]["get"]
        assert operation["security"] and {"200", "401", "403", "404", "422"}.issubset(operation["responses"])


def test_company_inventory_before_a_price_list(client, db_session, company_id, make_door_type, make_installer):
    door_type, installer = make_door_type(name="Current entrance"), make_installer()
    db_session.add(InstallerRateORM(company_id=company_id, installer_id=installer.id, door_type_id=door_type.id,
        price=Decimal("175"), effective_from=datetime.now(timezone.utc) - timedelta(days=1)))
    db_session.commit()
    response = client.get(f"{URL}/reconciliation")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["price_list_id"] is None and data["version"] is None and data["currency"] == "ILS"
    assert data["total"] == 1 and data["items"][0]["legacy_price"] == "175.00"
    assert data["items"][0]["legacy_variants"] == 1 and data["summary"]["multiple_rate_types"] == 0
    assert data["items"][0]["proposed_price"] is None and data["items"][0]["status"] == "MISSING_PROPOSED"
    assert client.get(URL).json()["total"] == 0


def test_empty_company_inventory(client):
    response = client.get(f"{URL}/reconciliation")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["items"] == [] and data["total"] == 0
    assert all(value == 0 for value in data["summary"].values())
