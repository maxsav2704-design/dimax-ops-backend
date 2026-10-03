from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM, ProjectAddonPlanORM
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.shared.infrastructure.db.base import utcnow

URL = "/api/v1/admin/price-lists"
PUBLIC = "/api/v1/public/price-approvals"


def confirm_version(client, items, expected=0):
    response = client.post(URL, json={"request_id": str(uuid4()), "expected_latest_version": expected,
        "reason": "Factory offer", "agreement_reference": "QA agreement", "items": items})
    assert response.status_code == 200, response.text
    version = response.json()
    issued = client.post(f'{URL}/{version["id"]}/approvals', json={"factory_name": "QA Factory",
        "recipient_name": "QA Representative", "recipient_email": "qa@example.com", "expires_in_hours": 24})
    assert issued.status_code == 200, issued.text
    token = urlsplit(issued.json()["confirmation_url"]).fragment
    preview = client.post(f"{PUBLIC}/preview", json={"token": token})
    assert preview.status_code == 200, preview.text
    response = client.post(f"{PUBLIC}/confirm", json={"token": token, "expected_version": version["version"],
        "snapshot_hash": preview.json()["snapshot_hash"], "signer_name": "QA Representative", "accepted": True})
    assert response.status_code == 200, response.text
    return {"id": version["id"], "token": token, "receipt_id": issued.json()["invitation"]["id"]}


@pytest.fixture()
def priced(client, db_session, company_id, make_door_type):
    door_type = make_door_type(name="Entrance")
    addon = AddonTypeORM(company_id=company_id, name="Adjustment", unit="pcs", default_installer_price=Decimal("9"))
    db_session.add(addon)
    db_session.commit()
    items = [{"kind": "DOOR", "target_id": str(door_type.id), "installer_price": "250.00"},
             {"kind": "ADDON", "target_id": str(addon.id), "installer_price": "9.00"}]
    case = confirm_version(client, items)
    return {**case, "door_type": door_type, "addon": addon, "items": items}


def check(client, case, **params):
    response = client.get(f'{URL}/{case["id"]}/reconciliation', params=params)
    assert response.status_code == 200, response.text
    return response.json()["application_check"]


def blockers(result):
    return {row["code"]: row["count"] for row in result["blockers"]}


def test_verified_data_does_not_claim_active_prices(client, priced):
    result = check(client, priced)
    assert result["status"] == "VERIFIED" and result["confirmed_at"]
    assert result["affects_earnings"] is False
    assert result["blockers"] == result["review"] == []


@pytest.mark.parametrize("mode", ["draft", "cancelled", "fake_confirmed"])
def test_status_alone_is_not_factory_evidence(client, priced, db_session, mode):
    db_session.execute(text("DELETE FROM factory_price_approvals WHERE price_list_id=:id"), {"id": priced["id"]})
    if mode != "fake_confirmed":
        db_session.execute(text("UPDATE factory_price_lists SET status='DRAFT' WHERE id=:id"), {"id": priced["id"]})
    db_session.commit()
    if mode == "cancelled":
        response = client.post(f'{URL}/{priced["id"]}/cancel', json={"reason": "Withdrawn offer"})
        assert response.status_code == 200, response.text
    result = check(client, priced)
    assert result["status"] == "BLOCKED"
    assert ("CONFIRMATION_MISSING" if mode == "fake_confirmed" else "NOT_CONFIRMED") in blockers(result)


@pytest.mark.parametrize("tamper", ["price", "hash", "snapshot", "empty_snapshot"])
def test_exact_confirmed_snapshot_is_required(client, priced, db_session, tamper):
    if tamper == "price":
        db_session.execute(text("UPDATE factory_price_list_items SET installer_price=999 WHERE price_list_id=:id"), {"id": priced["id"]})
    else:
        receipt = db_session.get(FactoryPriceApprovalORM, UUID(priced["receipt_id"]))
        if tamper == "hash":
            receipt.snapshot_hash = "0" * 64
        else:
            receipt.snapshot = {} if tamper == "empty_snapshot" else {**receipt.snapshot, "version": 99}
    db_session.commit()
    assert "CONFIRMATION_MISMATCH" in blockers(check(client, priced))
    if tamper == "empty_snapshot":
        assert client.post(f"{PUBLIC}/preview", json={"token": priced["token"]}).status_code == 409


def test_expired_link_does_not_expire_the_recorded_decision(client, priced, db_session):
    receipt = db_session.get(FactoryPriceApprovalORM, UUID(priced["receipt_id"]))
    receipt.created_at, receipt.confirmed_at, receipt.expires_at = utcnow() - timedelta(days=3), utcnow() - timedelta(days=2), utcnow() - timedelta(days=1)
    db_session.commit()
    assert check(client, priced)["status"] == "VERIFIED"
    assert client.post(f"{PUBLIC}/preview", json={"token": priced["token"]}).status_code == 404


def test_pending_amendment_does_not_disqualify_previous_confirmed_version(client, priced):
    response = client.post(URL, json={"request_id": str(uuid4()), "expected_latest_version": 1,
        "reason": "Requested amendment", "agreement_reference": "QA revision", "items": priced["items"]})
    assert response.status_code == 200, response.text
    assert check(client, priced)["status"] == "VERIFIED"


def test_new_confirmed_version_blocks_preparing_an_older_one(client, priced):
    newer = confirm_version(client, priced["items"], expected=1)
    assert "SUPERSEDED_CONFIRMED" in blockers(check(client, priced))
    assert check(client, newer)["status"] == "VERIFIED"


def test_all_current_work_types_need_prices_and_filters_cannot_hide_gaps(client, priced, db_session, company_id, make_door_type):
    make_door_type(name="Unquoted fire door")
    db_session.add(AddonTypeORM(company_id=company_id, name="Unquoted work", unit="hour"))
    db_session.commit()
    result = check(client, priced)
    assert blockers(result) == {"MISSING_DOOR_PRICES": 1, "MISSING_ADDON_PRICES": 1}
    assert check(client, priced, kind="ADDON", issues_only=True, limit=1, offset=1000) == result


@pytest.mark.parametrize("field,value", [("name", "Different work"), ("unit", "hour"), ("is_active", False)])
def test_changed_catalog_requires_reviewed_new_version(client, priced, db_session, field, value):
    setattr(priced["addon"], field, value)
    db_session.commit()
    assert ("UNAVAILABLE_WORK" if field == "is_active" else "CATALOG_CHANGED") in blockers(check(client, priced))


def test_pending_work_with_unavailable_type_is_not_hidden(client, priced, db_session, company_id, make_door_type):
    unavailable = make_door_type(name="Legacy unavailable type")
    unavailable.is_active = False
    project = ProjectORM(company_id=company_id, name="QA object", address="QA", status="OK")
    db_session.add(project)
    db_session.flush()
    db_session.add(DoorORM(company_id=company_id, project_id=project.id, door_type_id=unavailable.id, unit_label="A-101", our_price=Decimal("500")))
    db_session.commit()
    assert blockers(check(client, priced))["UNAVAILABLE_WORK"] == 1


def test_legacy_snapshots_and_unaccrued_work_require_a_decision(client, priced, db_session, company_id, make_installer):
    installer = make_installer()
    project = ProjectORM(company_id=company_id, name="QA object", address="QA", status="OK")
    db_session.add(project)
    db_session.flush()
    db_session.add_all([
        InstallerRateORM(company_id=company_id, installer_id=installer.id, door_type_id=priced["door_type"].id,
            price=Decimal("100"), effective_from=utcnow() - timedelta(days=1)),
        DoorORM(company_id=company_id, project_id=project.id, door_type_id=priced["door_type"].id, installer_id=installer.id,
            unit_label="A-101", our_price=Decimal("500"), installer_rate_snapshot=Decimal("100")),
        ProjectAddonPlanORM(company_id=company_id, project_id=project.id, addon_type_id=priced["addon"].id,
            qty_planned=Decimal("10"), installer_price=Decimal("9"), client_price=Decimal("20")),
        ProjectAddonFactORM(company_id=company_id, project_id=project.id, installer_id=installer.id,
            addon_type_id=priced["addon"].id, qty_done=Decimal("1.50"), done_at=utcnow()),
    ])
    db_session.commit()
    result = check(client, priced)
    assert result["status"] == "REVIEW_REQUIRED" and not result["affects_earnings"]
    assert {row["code"] for row in result["review"]} >= {"LEGACY_DIFFERENCES", "DOOR_SNAPSHOTS", "UNACCRUED_WORK"}
    assert result["blockers"] == []


def test_installer_surcharge_cannot_be_silently_added_to_confirmed_price(client, priced, db_session, company_id):
    project = ProjectORM(company_id=company_id, name="QA object", address="QA", status="OK")
    db_session.add(project)
    db_session.flush()
    db_session.add(DoorORM(company_id=company_id, project_id=project.id, door_type_id=priced["door_type"].id,
        unit_label="A-101", our_price=Decimal("500"), installer_rate_snapshot=Decimal("100"),
        apply_surcharge_to_installer=True, surcharge_pct=Decimal("125")))
    db_session.commit()
    assert blockers(check(client, priced))["INSTALLER_SURCHARGES"] == 1


def test_check_is_readonly_and_tenant_scoped(client, priced, db_session, company_id, make_door_type):
    make_door_type(name="FOREIGN PRIVATE TYPE", company=uuid4())
    tables = ("factory_price_lists", "factory_price_list_items", "factory_price_approvals", "completed_work",
              "doors", "project_addon_facts", "project_addon_plans", "installer_rates", "audit_logs", "sync_change_log", "outbox_messages")
    def snapshot():
        return {name: db_session.execute(text(
            f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb) FROM {name} t WHERE company_id=:cid"
        ), {"cid": company_id}).scalar_one() for name in tables}
    before = snapshot()
    result = check(client, priced)
    assert result["status"] == "VERIFIED" and "PRIVATE" not in str(result)
    assert snapshot() == before
    baseline = client.get(f"{URL}/reconciliation")
    assert baseline.status_code == 200 and baseline.json()["application_check"] is None
