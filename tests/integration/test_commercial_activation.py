"""Activation stage (0087): OWNER puts a factory-confirmed pair into effect, the rate resolver, the 10th-to-10th
period rule and the read-only period estimate. Nothing here creates a claim, an invoice or an installer earning."""
import runpy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.modules.accounting.application.agreement_service import CommercialRateResolver
from app.modules.accounting.domain.periods import CUTOVER, Period, local_day, period_for, period_for_day, periods_between
from app.modules.accounting.infrastructure.agreement_models import CommercialAgreementORM as Agreement
from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.modules.journal.domain.enums import JournalStatus
from app.modules.journal.infrastructure.models import JournalAddonItemORM, JournalDoorItemORM, JournalORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.models import InstallerRateORM
from tests.integration.test_commercial_approvals import PUBLIC, decision, invite, isolation, path, prepared  # noqa: F401
from tests.integration.test_commercial_contract_terms import save, terms_body  # noqa: F401
from tests.integration.test_commercial_drafts import (  # noqa: F401
    URL, contract, contract_body, create_price, owner_client, price_body,
)

TZ_IL = "Asia/Jerusalem"


@pytest.fixture(autouse=True)
def activation_isolation(isolation, db_session, company_id, monkeypatch):
    monkeypatch.setattr(settings, "COMMERCIAL_ACTIVATION_ENABLED", True)
    yield
    db_session.rollback()
    db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))
    for model in (JournalAddonItemORM, JournalDoorItemORM, JournalORM, DoorORM, Agreement):
        db_session.execute(delete(model).where(model.company_id == company_id))
    db_session.commit()


def agreements_path(contract):
    return f'{URL}/{contract["id"]}/agreements'


def confirmed(owner_client, contract, prepared, db_session):
    invitation, token = invite(owner_client, contract, prepared, db_session)
    result = owner_client.post(PUBLIC + '/confirm', json=decision(owner_client, token, db_session, invitation))
    assert result.status_code == 200, result.text
    return invitation


def full_installation_pair(owner_client, contract, prepared, db_session, terms_body):
    """A factory-confirmed pair whose terms bill full installations (the shared fixture bills by stages)."""
    latest = owner_client.get(f'{URL}/{contract["id"]}/terms?limit=1').json()["latest_version"]
    terms = save(owner_client, contract, {**terms_body, "request_id": str(uuid4()), "expected_latest_version": latest,
                                          "billing_basis": "FULL_INSTALLATION"})
    candidate = owner_client.get(f'{URL}/{contract["id"]}/approval-preview',
                                 params={"terms_id": terms["id"], "price_id": prepared["price_id"]}).json()
    return confirmed(owner_client, contract, {**prepared, "request_id": str(uuid4()), "terms_id": terms["id"],
                                               "snapshot_hash": candidate["snapshot_hash"]}, db_session)


def activation(approval_id, effective_from="2026-11-10", **extra):
    return {"request_id": str(uuid4()), "approval_id": approval_id, "effective_from": effective_from,
            "reason": "Owner puts the confirmed pair into effect", "accepted": True, **extra}


# ---- period rule -----------------------------------------------------------------------------------------------

def test_t01_period_boundary_in_jerusalem_across_dst():
    # 2026-11-09 23:59:59 Israel (UTC+2 after the October clock change) and 2026-11-10 00:00 are different periods.
    assert period_for(datetime(2026, 11, 9, 21, 59, 59, tzinfo=timezone.utc)) == Period(date(2026, 10, 10), date(2026, 11, 10))
    assert period_for(datetime(2026, 11, 9, 22, 0, 0, tzinfo=timezone.utc)) == Period(date(2026, 11, 10), date(2026, 12, 10))
    # Summer (UTC+3): 2027-06-09 23:59:59 local is 20:59:59Z; 21:00:00Z is already the 10th.
    assert period_for(datetime(2027, 6, 9, 20, 59, 59, tzinfo=timezone.utc)).start == date(2027, 5, 10)
    assert period_for(datetime(2027, 6, 9, 21, 0, 0, tzinfo=timezone.utc)).start == date(2027, 6, 10)
    assert period_for_day(date(2026, 12, 9)) == Period(date(2026, 11, 10), date(2026, 12, 10))
    assert period_for_day(date(2027, 1, 1)).start == date(2026, 12, 10) and period_for_day(date(2027, 1, 10)).start == date(2027, 1, 10)
    assert [p.start for p in periods_between(CUTOVER, date(2027, 1, 15))] == [date(2026, 11, 10), date(2026, 12, 10), date(2027, 1, 10)]
    assert period_for_day(CUTOVER).end == date(2026, 12, 9)
    with pytest.raises(ValueError):
        local_day(datetime(2026, 11, 10))


# ---- activation ------------------------------------------------------------------------------------------------

def test_owner_puts_confirmed_pair_into_effect_without_financial_effect(owner_client, contract, prepared, db_session, company_id, price_body):
    before = [db_session.scalar(select(func.count()).select_from(model)) for model in (InstallerRateORM, CompletedWorkORM)]
    approval = confirmed(owner_client, contract, prepared, db_session)
    page = owner_client.get(agreements_path(contract)).json()
    assert page["activation_enabled"] and page["current"] is None and page["cutover"] == "2026-11-10"
    body = activation(approval["id"])
    assert owner_client.post(agreements_path(contract), json={**body, "accepted": False}).status_code == 422
    assert owner_client.post(agreements_path(contract), json={**body, "effective_from": "2026-11-09"}).status_code == 422
    assert owner_client.post(agreements_path(contract), json={**body, "effective_from": "2026-01-01"}).status_code == 422
    result = owner_client.post(agreements_path(contract), json=body)
    assert result.status_code == 200, result.text
    row = result.json()
    assert row["approval_id"] == approval["id"] and row["effective_from"] == "2026-11-10" and row["effective_until"] is None
    assert row["terms_version"] == 1 and row["price_version"] == 1 and row["status"] == "SCHEDULED" and row["is_demo"]
    assert not row["usable_for_billing"]
    # Idempotent by request id; a different payload under the same id is refused; a second activation of the same decision too.
    assert owner_client.post(agreements_path(contract), json=body).json() == row
    assert owner_client.post(agreements_path(contract), json={**body, "effective_from": "2026-11-11"}).status_code == 409
    assert owner_client.post(agreements_path(contract), json=activation(approval["id"], "2026-12-10")).status_code == 409
    page = owner_client.get(agreements_path(contract)).json()
    assert page["total"] == 1 and page["items"][0]["id"] == row["id"]
    history = owner_client.get(path(contract)).json()["items"]
    assert history[0]["status"] == "CONFIRMED" and history[0]["agreement_id"] == row["id"]
    # The resolver answers only inside the effective range and only for positions of the confirmed price.
    door = next(line["target_id"] for line in price_body["items"] if line["kind"] == "INSTALLATION")
    addon = next(line["target_id"] for line in price_body["items"] if line["kind"] == "ADDON")
    rate = CommercialRateResolver.rate_for(db_session, company_id, contract["id"], kind="INSTALLATION", target_id=door, on_date=date(2026, 11, 15))
    assert rate is not None and rate.price_version == 1 and rate.agreement_id.hex == row["id"].replace("-", "")
    assert CommercialRateResolver.rate_for(db_session, company_id, contract["id"], kind="ADDON", target_id=addon, on_date=date(2026, 11, 10)) is not None
    assert CommercialRateResolver.rate_for(db_session, company_id, contract["id"], kind="INSTALLATION", target_id=door, on_date=date(2026, 11, 9)) is None
    assert CommercialRateResolver.rate_for(db_session, company_id, contract["id"], kind="INSTALLATION", target_id=uuid4(), on_date=date(2026, 11, 15)) is None
    assert CommercialRateResolver.rate_for(db_session, company_id, contract["id"], kind="STAGE", target_id=door, on_date=date(2026, 11, 15), stage_code="UNKNOWN_STAGE") is None
    assert [db_session.scalar(select(func.count()).select_from(model)) for model in (InstallerRateORM, CompletedWorkORM)] == before
    audit = db_session.scalars(select(AuditLogORM).where(AuditLogORM.company_id == company_id,
                                                         AuditLogORM.entity_type == "COMMERCIAL_AGREEMENT")).all()
    assert [log.action for log in audit] == ["ACTIVATE"] and audit[0].after["creates_claim"] is False


def test_unconfirmed_pending_or_revoked_decision_cannot_be_activated(owner_client, contract, prepared, db_session):
    invitation, _ = invite(owner_client, contract, prepared, db_session)
    assert owner_client.post(agreements_path(contract), json=activation(invitation["id"])).status_code == 409
    assert owner_client.post(path(contract) + '/' + invitation["id"] + '/revoke', json={"reason": "Cancelled"}).status_code == 200
    assert owner_client.post(agreements_path(contract), json=activation(invitation["id"])).status_code == 409
    assert owner_client.post(agreements_path(contract), json=activation(str(uuid4()))).status_code == 404


def test_next_pair_closes_the_previous_agreement_gap_free_and_history_is_immutable(owner_client, contract, prepared, db_session, company_id, terms_body, price_body):
    first = confirmed(owner_client, contract, prepared, db_session)
    one = owner_client.post(agreements_path(contract), json=activation(first["id"])).json()
    # Amended versions, confirmed by the factory again.
    terms = save(owner_client, contract, {**terms_body, "request_id": str(uuid4()), "expected_latest_version": 1})
    price = create_price(owner_client, contract, {**price_body, "request_id": str(uuid4()), "expected_latest_version": 1,
        "reason": "Amendment", "items": [{**line, "unit_price_ex_vat": "777.00"} for line in price_body["items"]]})
    candidate = owner_client.get(f'{URL}/{contract["id"]}/approval-preview', params={"terms_id": terms["id"], "price_id": price["id"]}).json()
    second = confirmed(owner_client, contract, {**prepared, "request_id": str(uuid4()), "terms_id": terms["id"],
                                                 "price_id": price["id"], "snapshot_hash": candidate["snapshot_hash"]}, db_session)
    assert owner_client.post(agreements_path(contract), json=activation(second["id"], "2026-11-10")).status_code == 409
    two = owner_client.post(agreements_path(contract), json=activation(second["id"], "2026-12-10"))
    assert two.status_code == 200, two.text
    page = owner_client.get(agreements_path(contract)).json()
    by_id = {row["id"]: row for row in page["items"]}
    assert by_id[one["id"]]["effective_until"] == "2026-12-09" and by_id[two.json()["id"]]["effective_until"] is None
    door = next(line["target_id"] for line in price_body["items"] if line["kind"] == "INSTALLATION")
    nov = CommercialRateResolver.rate_for(db_session, company_id, contract["id"], kind="INSTALLATION", target_id=door, on_date=date(2026, 11, 20))
    dec = CommercialRateResolver.rate_for(db_session, company_id, contract["id"], kind="INSTALLATION", target_id=door, on_date=date(2026, 12, 15))
    assert nov.price_version == 1 and dec.price_version == 2 and dec.unit_price_ex_vat == Decimal("777.00")
    assert CommercialRateResolver.rate_for(db_session, company_id, contract["id"], kind="INSTALLATION", target_id=door, on_date=date(2026, 12, 9)).price_version == 1
    closed = db_session.get(Agreement, one["id"])
    for change in (lambda: setattr(closed, "reason", "rewritten"), lambda: setattr(closed, "effective_until", date(2026, 12, 20)),
                   lambda: db_session.delete(closed)):
        change()
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()
    db_session.expire_all()
    assert db_session.get(Agreement, one["id"]).effective_until == date(2026, 12, 9)


def test_only_owner_in_the_same_company_and_only_with_the_flag(owner_client, contract, prepared, db_session, admin_user, monkeypatch):
    approval = confirmed(owner_client, contract, prepared, db_session)
    profile = db_session.query(AdminProfileORM).filter_by(user_id=admin_user.id).one()
    profile.admin_scope = "OPERATIONS"
    db_session.commit()
    from dataclasses import replace
    from app.api.v1.deps import require_admin
    owner_client.app.dependency_overrides[require_admin] = lambda: replace(admin_user, admin_scope="OPERATIONS")
    assert owner_client.get(agreements_path(contract)).status_code == 403
    assert owner_client.post(agreements_path(contract), json=activation(approval["id"])).status_code == 403
    owner_client.app.dependency_overrides[require_admin] = lambda: replace(admin_user, admin_scope="OWNER")
    profile.admin_scope = "OWNER"
    db_session.commit()
    assert owner_client.get(f'{URL}/{uuid4()}/agreements').status_code == 404
    monkeypatch.setattr(settings, "COMMERCIAL_ACTIVATION_ENABLED", False)
    assert owner_client.get(agreements_path(contract)).json()["activation_enabled"] is False
    assert owner_client.post(agreements_path(contract), json=activation(approval["id"])).status_code == 409
    assert owner_client.get(f'{URL}/{contract["id"]}/periods').status_code == 409
    monkeypatch.setattr(settings, "COMMERCIAL_ACTIVATION_ENABLED", True)
    monkeypatch.setenv("APP_ENV", "production")
    assert owner_client.post(agreements_path(contract), json=activation(approval["id"])).status_code == 409


# ---- period estimate -------------------------------------------------------------------------------------------

def signed_journal(db_session, company_id, project, door_type_id, *, door_days, addon=None):
    journal = JournalORM(company_id=company_id, project_id=project.id, status=JournalStatus.ARCHIVED,
                         signed_at=datetime(2026, 12, 20, 10, tzinfo=timezone.utc), signer_name="Site signer",
                         snapshot_version=1, pdf_locale="en")
    db_session.add(journal)
    db_session.flush()
    for index, day in enumerate(door_days):
        door = DoorORM(company_id=company_id, project_id=project.id, door_type_id=door_type_id,
                       unit_label=f"E-{index}-{uuid4().hex[:4]}", status="INSTALLED", version=1, our_price=Decimal("500"), is_locked=False)
        db_session.add(door)
        db_session.flush()
        db_session.add(JournalDoorItemORM(company_id=company_id, journal_id=journal.id, door_id=door.id, unit_label=door.unit_label,
                                          door_type_id=door_type_id, installed_at=day))
    if addon:
        addon_type, qty, done = addon
        db_session.add(JournalAddonItemORM(company_id=company_id, journal_id=journal.id, addon_fact_id=uuid4(), addon_type_id=addon_type.id,
                                           addon_name=addon_type.name, unit=addon_type.unit, qty_done=qty, done_at=done))
    db_session.commit()
    return journal


def test_period_estimate_values_signed_lines_at_the_rate_in_effect(owner_client, contract, prepared, db_session, company_id, price_body, terms_body, monkeypatch):
    approval = full_installation_pair(owner_client, contract, prepared, db_session, terms_body)
    assert owner_client.post(agreements_path(contract), json=activation(approval["id"], "2026-11-10")).status_code == 200
    monkeypatch.setattr("app.modules.accounting.application.estimate_service.utcnow",
                        lambda: datetime(2026, 12, 20, 12, tzinfo=timezone.utc))
    door_type = next(line["target_id"] for line in price_body["items"] if line["kind"] == "INSTALLATION")
    addon_type = db_session.scalar(select(AddonTypeORM).where(AddonTypeORM.company_id == company_id))
    project = ProjectORM(company_id=company_id, name="Estimate site", address="Synthetic", status="OK")
    db_session.add(project)
    db_session.flush()
    il = lambda y, m, d, h=12: datetime(y, m, d, h, tzinfo=timezone.utc)  # noqa: E731
    # Two doors in November, one on 9 Nov 23:30 local (= 21:30Z, before the cutover), one undated; 2.5 h addon in November.
    signed_journal(db_session, company_id, project, door_type, door_days=[il(2026, 11, 15), il(2026, 11, 9, 21), None],
                   addon=(addon_type, Decimal("2.5"), il(2026, 11, 20)))
    signed_journal(db_session, company_id, project, door_type, door_days=[il(2026, 12, 12)])
    # An unsigned journal is never counted.
    draft = JournalORM(company_id=company_id, project_id=project.id, status=JournalStatus.DRAFT, snapshot_version=1, pdf_locale="en")
    db_session.add(draft)
    db_session.commit()
    page = owner_client.get(f'{URL}/{contract["id"]}/periods')
    assert page.status_code == 200, page.text
    data = page.json()
    assert data["estimate_only"] and data["undated_lines"] == 1 and data["current_start"] == "2026-12-10"
    assert [item["start"] for item in data["items"]] == ["2026-12-10", "2026-11-10"]
    nov, dec = data["items"][1], data["items"][0]
    door_price = Decimal(next(line["unit_price_ex_vat"] for line in price_body["items"] if line["kind"] == "INSTALLATION"))
    addon_price = Decimal(next(line["unit_price_ex_vat"] for line in price_body["items"] if line["kind"] == "ADDON"))
    assert nov["signed_journals"] == 1 and nov["rated_lines"] == 2 and nov["unrated_lines"] == 0 and nov["vat"] is None, nov
    assert Decimal(nov["amount_ex_vat"]) == (door_price + Decimal("2.5") * addon_price).quantize(Decimal("0.01"))
    assert dec["rated_lines"] == 1 and Decimal(dec["amount_ex_vat"]) == door_price
    detail = owner_client.get(f'{URL}/{contract["id"]}/periods/2026-11-10').json()
    assert {line["reason"] for line in detail["lines"]} == {"RATED"} and len(detail["lines"]) == 2
    assert all(line["project_name"] == "Estimate site" for line in detail["lines"])
    assert owner_client.get(f'{URL}/{contract["id"]}/periods/2026-10-10').status_code == 404
    assert owner_client.get(f'{URL}/{contract["id"]}/periods/2026-11-11').status_code == 404
    assert owner_client.get(f'{URL}/{contract["id"]}/periods/2027-01-10').status_code == 404
    # Before the accounting start only the first period is listed, empty, so the office can see where lines will land.
    monkeypatch.setattr("app.modules.accounting.application.estimate_service.utcnow",
                        lambda: datetime(2026, 10, 23, 12, tzinfo=timezone.utc))
    early = owner_client.get(f'{URL}/{contract["id"]}/periods').json()
    assert [item["start"] for item in early["items"]] == ["2026-11-10"] and early["current_start"] == "2026-11-10"
    assert owner_client.get(f'{URL}/{contract["id"]}/periods/2026-11-10').status_code == 200
    assert owner_client.get(f'{URL}/{contract["id"]}/periods/2026-12-10').status_code == 404


def test_estimate_marks_lines_without_agreement_or_rate_and_stage_contracts(owner_client, contract, prepared, db_session, company_id, price_body, terms_body, monkeypatch, make_door_type):
    monkeypatch.setattr("app.modules.accounting.application.estimate_service.utcnow",
                        lambda: datetime(2026, 12, 20, 12, tzinfo=timezone.utc))
    door_type = next(line["target_id"] for line in price_body["items"] if line["kind"] == "INSTALLATION")
    other_type = make_door_type(name="Unpriced door")
    project = ProjectORM(company_id=company_id, name="Backlog site", address="Synthetic", status="OK")
    db_session.add(project)
    db_session.flush()
    il = lambda y, m, d: datetime(y, m, d, 12, tzinfo=timezone.utc)  # noqa: E731
    signed_journal(db_session, company_id, project, door_type, door_days=[il(2026, 11, 15)])
    signed_journal(db_session, company_id, project, other_type.id, door_days=[il(2026, 11, 16)])
    # No agreement yet: every line waits.
    nov = owner_client.get(f'{URL}/{contract["id"]}/periods/2026-11-10').json()
    assert nov["rated_lines"] == 0 and nov["unrated_lines"] == 2 and {l["reason"] for l in nov["lines"]} == {"NO_AGREEMENT"}
    approval = full_installation_pair(owner_client, contract, prepared, db_session, terms_body)
    assert owner_client.post(agreements_path(contract), json=activation(approval["id"], "2026-11-10")).status_code == 200
    nov = owner_client.get(f'{URL}/{contract["id"]}/periods/2026-11-10').json()
    reasons = {l["label"][:2]: l["reason"] for l in nov["lines"]}
    assert nov["rated_lines"] == 1 and nov["unrated_lines"] == 1 and "NO_RATE" in reasons.values(), nov
    # A stage-based contract is not estimated until stage facts exist (owner's decision 2026-10-23).
    staged = save(owner_client, contract, {**terms_body, "request_id": str(uuid4()), "expected_latest_version": 2, "billing_basis": "STAGES"})
    price = create_price(owner_client, contract, {**price_body, "request_id": str(uuid4()), "expected_latest_version": 1, "reason": "Stage pricing"})
    candidate = owner_client.get(f'{URL}/{contract["id"]}/approval-preview', params={"terms_id": staged["id"], "price_id": price["id"]}).json()
    second = confirmed(owner_client, contract, {**prepared, "request_id": str(uuid4()), "terms_id": staged["id"], "price_id": price["id"],
                                                 "snapshot_hash": candidate["snapshot_hash"]}, db_session)
    assert owner_client.post(agreements_path(contract), json=activation(second["id"], "2026-12-10")).status_code == 200
    signed_journal(db_session, company_id, project, door_type, door_days=[il(2026, 12, 15)])
    dec = owner_client.get(f'{URL}/{contract["id"]}/periods/2026-12-10').json()
    assert dec["rated_lines"] == 0 and dec["unrated_lines"] == 1 and dec["lines"][0]["reason"] == "STAGES_NOT_SUPPORTED"
    assert nov["blocked_reason"] is None


def test_estimate_is_blocked_while_two_contracts_are_in_effect(owner_client, contract, contract_body, prepared, db_session, company_id, terms_body, price_body, monkeypatch):
    monkeypatch.setattr("app.modules.accounting.application.estimate_service.utcnow",
                        lambda: datetime(2026, 12, 20, 12, tzinfo=timezone.utc))
    approval = confirmed(owner_client, contract, prepared, db_session)
    assert owner_client.post(agreements_path(contract), json=activation(approval["id"])).status_code == 200
    other = owner_client.post(URL, json={**contract_body, "request_id": str(uuid4()), "reference": "SECOND-FACTORY"}).json()
    terms = save(owner_client, other, {**terms_body, "request_id": str(uuid4()), "expected_latest_version": 0})
    price = create_price(owner_client, other, {**price_body, "request_id": str(uuid4()), "expected_latest_version": 0})
    candidate = owner_client.get(f'{URL}/{other["id"]}/approval-preview', params={"terms_id": terms["id"], "price_id": price["id"]}).json()
    second = confirmed(owner_client, other, {**prepared, "request_id": str(uuid4()), "terms_id": terms["id"], "price_id": price["id"],
                                              "snapshot_hash": candidate["snapshot_hash"]}, db_session)
    assert owner_client.post(agreements_path(other), json=activation(second["id"])).status_code == 200
    page = owner_client.get(f'{URL}/{contract["id"]}/periods').json()
    assert all(item["blocked_reason"] == "MULTIPLE_CONTRACTS" and item["rated_lines"] == 0 for item in page["items"])


def test_downgrade_refuses_to_discard_agreements(owner_client, contract, prepared, db_session, monkeypatch):
    approval = confirmed(owner_client, contract, prepared, db_session)
    assert owner_client.post(agreements_path(contract), json=activation(approval["id"])).status_code == 200
    downgrade = runpy.run_path("alembic/versions/0087_commercial_agreements.py")["downgrade"]
    monkeypatch.setitem(downgrade.__globals__, "op", Operations(MigrationContext.configure(db_session.connection())))
    with pytest.raises(RuntimeError, match="agreement history"):
        downgrade()
    db_session.rollback()
