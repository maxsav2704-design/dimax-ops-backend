from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.audit.application.service import AuditService
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.modules.sync.application.price_resolution_service import PriceConflictResolutionService
from app.modules.sync.application.price_review_dto import ResolvePriceConflict
from app.modules.sync.application.price_review_service import PriceConflictReviewService
from app.modules.sync.infrastructure.models import SyncPriceResolutionORM
from app.shared.domain.errors import NotFound
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_earnings import activate, assert_applied, case, earning, submit
from test_factory_price_timeline import confirmed
from test_offline_execution_authority import retained
from test_price_conflict_resolution import clean_test_decisions


def preview(client, url, at):
    correction = {"performed_at": at.isoformat(), "evidence_reference": "Site work log QA-2026, confirmed by supervisor"}
    response = client.post(url + "/execution-review", json=correction)
    assert response.status_code == 200, response.text
    assert response.json()["resolution_available"] is True, response.text
    return correction, {"request_id": str(uuid4()), "review_token": response.json()["review_token"],
        "execution_correction": correction, "confirm_execution_evidence": True,
        "reason": "Checked the work date and assignment against the independent site record"}


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
@pytest.mark.parametrize("clock", ["missing", "naive", "future", "before_creation", "unknown_zone"])
def test_corrects_time_with_evidence_without_rewriting_command(case, db_session, client_admin_real_uow, kind, channel, clock):
    version, activation = activate(case)
    at = {"missing": None, "naive": activation.effective_from.replace(tzinfo=None),
        "future": utcnow() + timedelta(days=1), "before_creation": utcnow() - timedelta(days=1),
        "unknown_zone": None}[clock]
    payload = {"price_list_id": str(version.id), **({"base_version": 0} if kind == "DOOR" else {})}
    event_id = str(uuid4())
    submit(case, kind, channel, at, event_id, payload)
    row, url = retained(db_session, case, channel)
    if clock == "unknown_zone":
        row.client_happened_at, row.client_time_has_timezone = activation.effective_from, None
        db_session.commit()
    original = PriceConflictReviewService.original(row, "sync_event" if channel == "sync" else "sync_queue")
    assert client_admin_real_uow.get(url).json()["time_correction_available"] is True
    correction, body = preview(client_admin_real_uow, url, activation.effective_from)
    retained(db_session, case, channel)  # Preview is read-only, not an accrual.
    assert client_admin_real_uow.post(url + "/resolve", json={**body, "confirm_execution_evidence": False}).status_code == 409
    activate(case, expected=1, previous=version.id, door_price="300", addon_price="12")
    response = client_admin_real_uow.post(url + "/resolve", json=body)
    assert response.status_code == 200, response.text
    assert client_admin_real_uow.post(url + "/resolve", json=body).json() == response.json()
    changed = {**body, "execution_correction": {**correction, "evidence_reference": "Different independent evidence"}}
    assert client_admin_real_uow.post(url + "/resolve", json=changed).status_code == 409
    work, proof = earning(db_session, case)
    assert work.completed_at == proof.performed_at == activation.effective_from
    assert proof.price_list_id == version.id
    assert work.amount_snapshot == Decimal("250" if kind == "DOOR" else "13.50")
    db_session.refresh(row)
    assert PriceConflictReviewService.original(row, original["source"]) == original
    decision = db_session.query(SyncPriceResolutionORM).filter_by(company_id=case.company).one()
    assert decision.original_command == original
    assert decision.quote_snapshot["execution_correction"]["evidence_reference"] == correction["evidence_reference"]
    assert decision.quote_snapshot["execution_evidence_confirmed"] is True
    audit = db_session.query(AuditLogORM).filter_by(company_id=case.company, action="SYNC_FACTORY_PRICE_RESOLVED").one()
    assert audit.after["execution_correction"] == decision.quote_snapshot["execution_correction"]
    if clock != "unknown_zone":
        assert_applied(submit(case, kind, channel, at, event_id, payload), channel)
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 1
    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE sync_price_resolutions SET quote_snapshot='{}' WHERE id=:id"), {"id": decision.id})
    db_session.rollback()


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_corrected_legacy_time_uses_first_confirmed_price(case, db_session, client_admin_real_uow, kind, channel):
    at = utcnow()
    first, _ = activate(case)
    activate(case, expected=1, previous=first.id, door_price="300", addon_price="12")
    submit(case, kind, channel, None, extra_payload={"base_version": 0} if kind == "DOOR" else {})
    _, url = retained(db_session, case, channel)
    _, body = preview(client_admin_real_uow, url, at)
    response = client_admin_real_uow.post(url + "/resolve", json=body)
    assert response.status_code == 200, response.text
    work, proof = earning(db_session, case)
    assert proof.price_list_id == first.id and proof.selection == "FIRST_CONFIRMED_LEGACY"
    assert work.amount_snapshot == Decimal("250" if kind == "DOOR" else "13.50")


@pytest.mark.parametrize("field,value", [("performed_at", "2026-01-01T12:00:00"),
    ("performed_at", None), ("evidence_reference", "   "), ("evidence_reference", "x" * 501),
    ("amount", "1"), ("rate", "1"), ("price_list_id", str(uuid4()))])
def test_correction_rejects_untrusted_fields(case, db_session, client_admin_real_uow, field, value):
    _, activation = activate(case)
    submit(case, "DOOR", "batch", None)
    _, url = retained(db_session, case, "batch")
    correction, body = preview(client_admin_real_uow, url, activation.effective_from)
    correction = {**correction, field: value}
    assert client_admin_real_uow.post(url + "/execution-review", json=correction).status_code == 422
    assert client_admin_real_uow.post(url + "/resolve", json={**body, "execution_correction": correction}).status_code == 422
    retained(db_session, case, "batch")


@pytest.mark.parametrize("change", ["future", "before_creation", "date", "evidence", "receipt", "assignment", "version", "locked", "permission"])
def test_correction_rechecks_evidence_and_work_under_locks(case, db_session, client_admin_real_uow, change):
    _, activation = activate(case)
    submit(case, "DOOR", "batch", None)
    row, url = retained(db_session, case, "batch")
    correction, body = preview(client_admin_real_uow, url, activation.effective_from)
    door = db_session.get(DoorORM, case.door)
    if change in {"future", "before_creation", "date"}:
        at = {"future": utcnow() + timedelta(days=1), "before_creation": utcnow() - timedelta(days=1),
              "date": row.created_at}[change]
        body["execution_correction"] = {**correction, "performed_at": at.isoformat()}
    elif change == "evidence":
        body["execution_correction"] = {**correction, "evidence_reference": "Different site record reference"}
    elif change == "receipt":
        row.created_at -= timedelta(days=1)
    elif change == "assignment":
        door.installer_id = None
    elif change == "version":
        door.version += 1
    elif change == "locked":
        door.is_locked = True
    else:
        db_session.query(AdminProfileORM).filter_by(user_id=case.actor).one().can_view_rates = False
    db_session.commit()
    response = client_admin_real_uow.post(url + "/resolve", json=body)
    assert response.status_code == (403 if change == "permission" else 409), response.text
    retained(db_session, case, "batch")
    assert db_session.query(SyncPriceResolutionORM).filter_by(company_id=case.company).count() == 0


def test_time_correction_does_not_supply_missing_factory_price(case, db_session, client_admin_real_uow):
    at = utcnow()
    confirmed(case.company, case.actor, case.items[:1])  # First list has no addon price.
    activate(case, expected=1)
    submit(case, "ADDON", "batch", None)
    _, url = retained(db_session, case, "batch")
    correction = {"performed_at": at.isoformat(), "evidence_reference": "Independent site log QA-2026"}
    response = client_admin_real_uow.post(url + "/execution-review", json=correction)
    assert response.status_code == 200, response.text
    assert response.json()["analysis_code"] == "MISSING_FACTORY_PRICE"
    assert response.json()["resolution_available"] is False
    body = {"request_id": str(uuid4()), "review_token": "0" * 64, "reason": "Do not replace missing factory prices",
            "execution_correction": correction, "confirm_execution_evidence": True}
    assert client_admin_real_uow.post(url + "/resolve", json=body).status_code == 409
    retained(db_session, case, "batch")


def test_valid_time_cannot_be_changed_to_choose_a_different_price(case, db_session, client_admin_real_uow):
    first, a1 = activate(case)
    _, a2 = activate(case, expected=1, previous=first.id)
    submit(case, "DOOR", "batch", a1.effective_from)
    _, url = retained(db_session, case, "batch")
    response = client_admin_real_uow.post(url + "/execution-review", json={"performed_at": a2.effective_from.isoformat(),
        "evidence_reference": "Attempted date change of valid historical evidence"})
    assert response.status_code == 409, response.text
    retained(db_session, case, "batch")


@pytest.mark.parametrize("scope,rates,expected", [("OWNER", True, 200), ("OPERATIONS", True, 200),
    ("OPERATIONS", False, 403), ("FINANCE", True, 403), ("VIEWER", True, 403), ("INSTALLER", False, 403)])
def test_live_auth_protects_both_correction_stages(case, db_session, client_admin_real_uow, client_raw, make_user, scope, rates, expected):
    from app.modules.identity.domain.enums import UserRole
    _, activation = activate(case)
    submit(case, "DOOR", "batch", None)
    _, url = retained(db_session, case, "batch")
    correction, body = preview(client_admin_real_uow, url, activation.effective_from)
    user = make_user(role=UserRole.INSTALLER if scope == "INSTALLER" else UserRole.ADMIN)
    if scope != "INSTALLER":
        profile = db_session.query(AdminProfileORM).filter_by(user_id=user.id).one()
        profile.admin_scope, profile.can_view_rates = scope, rates
        db_session.commit()
    assert client_raw.post(url + "/execution-review", json=correction).status_code == 401
    login = client_raw.post("/api/v1/auth/login", json={"company_id": str(case.company),
        "email": user.email, "password": "secret123", "device_id": "time-review-test"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f'Bearer {login.json()["access_token"]}'}
    assert client_raw.post(url + "/execution-review", json=correction, headers=headers).status_code == expected
    response = client_raw.post(url + "/resolve", json=body, headers=headers)
    assert response.status_code == expected, response.text


def test_other_tenant_cannot_read_correction(case, db_session, client_admin_real_uow):
    _, activation = activate(case)
    submit(case, "DOOR", "batch", None)
    row, url = retained(db_session, case, "batch")
    _, body = preview(client_admin_real_uow, url, activation.effective_from)
    with pytest.raises(NotFound), SqlAlchemyUnitOfWork() as uow:
        PriceConflictReviewService.get(uow, company_id=uuid4(), source="sync_queue", item_id=row.id,
            execution_correction=ResolvePriceConflict(**body).execution_correction)


def test_correction_audit_failure_rolls_back_everything(case, db_session, client_admin_real_uow, monkeypatch):
    _, activation = activate(case)
    submit(case, "DOOR", "batch", None)
    row, url = retained(db_session, case, "batch")
    _, body = preview(client_admin_real_uow, url, activation.effective_from)
    original_add = AuditService.add
    def fail_audit(*args, **kwargs):
        if kwargs["action"] == "SYNC_FACTORY_PRICE_RESOLVED":
            raise RuntimeError("Audit unavailable")
        return original_add(*args, **kwargs)
    monkeypatch.setattr(AuditService, "add", fail_audit)
    with pytest.raises(RuntimeError, match="Audit unavailable"), SqlAlchemyUnitOfWork() as uow:
        PriceConflictResolutionService.resolve(uow, company_id=case.company, actor_user_id=case.actor,
            source="sync_queue", item_id=row.id, body=ResolvePriceConflict(**body))
    retained(db_session, case, "batch")
    assert db_session.query(SyncPriceResolutionORM).filter_by(company_id=case.company).count() == 0
