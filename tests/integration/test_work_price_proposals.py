from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM
from app.modules.audit.application.service import AuditService
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.modules.sync.application.price_review_service import PriceConflictReviewService
from app.modules.sync.application.work_price_proposal_dto import CreateWorkPriceProposal
from app.modules.sync.application.work_price_proposal_service import WorkPriceProposalService
from app.modules.sync.infrastructure.models import SyncEventORM, SyncQueueItemORM, WorkPriceProposalORM
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_earnings import activate, case, submit
from test_factory_price_timeline import confirmed


@pytest.fixture(autouse=True)
def clean_test_proposals(db_session, company_id):
    yield
    db_session.rollback()
    if db_session.query(WorkPriceProposalORM).filter_by(company_id=company_id).first():
        assert db_session.execute(text("SELECT current_database()")).scalar_one().endswith("_tests")
        db_session.execute(text("ALTER TABLE work_price_proposals DISABLE TRIGGER work_price_proposal_immutable"))
        db_session.execute(text("DELETE FROM work_price_proposals WHERE company_id=:cid"), {"cid": company_id})
        db_session.execute(text("ALTER TABLE work_price_proposals ENABLE TRIGGER work_price_proposal_immutable"))
        db_session.commit()


def missing(case, db, kind="DOOR", channel="batch", legacy=False):
    items = case.items
    case.items = [item for item in items if item["kind"] != kind]
    if legacy:
        at = utcnow()
        first = confirmed(case.company, case.actor, case.items)
        case.items = items
        activate(case, expected=1)
    else:
        first, _ = activate(case)
        case.items = items
        at = utcnow()
    response = submit(case, kind, channel, at, extra_payload={"base_version": 0} if kind == "DOOR" else {})
    assert response.status_code == 200, response.text
    model = SyncEventORM if channel == "sync" else SyncQueueItemORM
    row = db.query(model).filter_by(company_id=case.company).one()
    assert (row.apply_error if channel == "sync" else row.conflict_code) == "CONFLICT_FACTORY_PRICE"
    source = "sync_event" if channel == "sync" else "sync_queue"
    return row, f"/api/v1/admin/sync/price-conflicts/{source}/{row.id}/work-price-proposals", first


def proposal_body(client, url, **overrides):
    correction = overrides.get("execution_correction")
    response = client.post(url + "/review", json={"execution_correction": correction})
    assert response.status_code == 200, response.text
    return {"request_id": str(uuid4()), "review_token": response.json()["review_token"], "rate": "9.01",
        "reason": "Rate absent from execution-time factory list", "agreement_reference": "Factory discussion QA-2026-10",
        "execution_evidence": "Site work record QA-2026-10, date and assignment verified",
        "confirm_execution_evidence": True, **overrides}


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
@pytest.mark.parametrize("legacy", [False, True])
def test_proposal_is_scoped_immutable_and_never_accrues(case, db_session, client_admin_real_uow, kind, channel, legacy):
    row, url, first = missing(case, db_session, kind, channel, legacy)
    source = "sync_event" if channel == "sync" else "sync_queue"
    original = PriceConflictReviewService.original(row, source)
    body = proposal_body(client_admin_real_uow, url)
    response = client_admin_real_uow.post(url, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["version"] == 1 and result["status"] == "PREPARED"
    assert result["affects_earnings"] is result["invitation_sent"] is False
    assert Decimal(result["amount"]) == Decimal("9.01" if kind == "DOOR" else "13.52")
    assert result["scope"]["missing_price"]["price_list_id"] == str(first.id)
    assert result["scope"]["missing_price"]["selection"] == ("FIRST_CONFIRMED_LEGACY" if legacy else "AT_EXECUTION")
    assert result["scope"]["installer_id"] == str(case.installer)
    assert result["scope"]["project_id"] == str(case.project)
    assert client_admin_real_uow.post(url, json=body).json() == result
    assert client_admin_real_uow.post(url, json={**body, "rate": "9.02"}).status_code == 409
    assert client_admin_real_uow.post(url, json={**body, "request_id": str(uuid4())}).status_code == 409
    reviewed = client_admin_real_uow.post(url + "/review", json={}).json()
    assert reviewed["latest"] == result
    db_session.expire_all()
    assert PriceConflictReviewService.original(row, source) == original
    assert db_session.get(DoorORM, case.door).status == DoorStatus.IN_PROGRESS
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(ProjectAddonFactORM).filter_by(company_id=case.company).count() == 0
    stored = db_session.query(WorkPriceProposalORM).filter_by(company_id=case.company).one()
    assert stored.snapshot["original_command"] == original
    assert db_session.query(AuditLogORM).filter_by(company_id=case.company, action="WORK_PRICE_PROPOSED").count() == 1
    for command in ("UPDATE work_price_proposals SET rate=1 WHERE id=:id", "DELETE FROM work_price_proposals WHERE id=:id"):
        with pytest.raises(DBAPIError):
            db_session.execute(text(command), {"id": stored.id})
        db_session.rollback()


def test_new_terms_append_version_without_editing_previous(case, db_session, client_admin_real_uow):
    _, url, _ = missing(case, db_session, "ADDON")
    first = client_admin_real_uow.post(url, json=proposal_body(client_admin_real_uow, url)).json()
    second = client_admin_real_uow.post(url, json=proposal_body(client_admin_real_uow, url, rate="11.00")).json()
    assert second["version"] == 2 and second["id"] != first["id"]
    assert Decimal(second["amount"]) == Decimal("16.50")
    rows = db_session.query(WorkPriceProposalORM).filter_by(company_id=case.company).order_by(WorkPriceProposalORM.version).all()
    assert len(rows) == 2 and rows[0].rate == Decimal("9.01")
    assert rows[1].snapshot["previous_proposal_id"] == first["id"]


@pytest.mark.parametrize("change", ["assignment", "version", "locked", "installed", "quantity", "unit", "inactive_addon", "permission", "payload", "time"])
def test_stale_review_or_invalid_work_cannot_be_saved(case, db_session, client_admin_real_uow, change):
    kind = "ADDON" if change in ("quantity", "unit", "inactive_addon") else "DOOR"
    row, url, _ = missing(case, db_session, kind)
    body = proposal_body(client_admin_real_uow, url)
    door = db_session.get(DoorORM, case.door)
    if change == "assignment":
        door.installer_id = None
    elif change == "version":
        door.version += 1
    elif change == "locked":
        door.is_locked = True
    elif change == "installed":
        door.status = DoorStatus.INSTALLED
    elif change == "quantity":
        row.payload = {**row.payload, "qty_done": "2"}
    elif change == "unit":
        db_session.get(AddonTypeORM, case.addon).unit = "hours"
    elif change == "inactive_addon":
        db_session.get(AddonTypeORM, case.addon).is_active = False
    elif change == "permission":
        db_session.query(AdminProfileORM).filter_by(user_id=case.actor).one().can_view_rates = False
    elif change == "payload":
        row.payload = {**row.payload, "rate": "1"}
    else:
        row.client_happened_at = None
    db_session.commit()
    response = client_admin_real_uow.post(url, json=body)
    assert response.status_code in (403, 409, 422), response.text
    assert db_session.query(WorkPriceProposalORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


@pytest.mark.parametrize("scope,rates,expected", [
    ("OWNER", True, 200), ("OPERATIONS", True, 200), ("OPERATIONS", False, 403),
    ("FINANCE", True, 403), ("VIEWER", True, 403), ("INSTALLER", False, 403),
])
def test_real_jwt_permissions(case, db_session, client_admin_real_uow, client_raw, make_user, scope, rates, expected):
    from app.modules.identity.domain.enums import UserRole
    _, url, _ = missing(case, db_session)
    body = proposal_body(client_admin_real_uow, url)
    user = make_user(role=UserRole.INSTALLER if scope == "INSTALLER" else UserRole.ADMIN)
    if scope != "INSTALLER":
        profile = db_session.query(AdminProfileORM).filter_by(user_id=user.id).one()
        profile.admin_scope, profile.can_view_rates = scope, rates
        db_session.commit()
    assert client_raw.post(url + "/review", json={}).status_code == 401
    assert client_raw.post(url, json=body).status_code == 401
    login = client_raw.post("/api/v1/auth/login", json={"company_id": str(case.company),
        "email": user.email, "password": "secret123", "device_id": "work-price-proposal"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f'Bearer {login.json()["access_token"]}'}
    assert client_raw.post(url + "/review", json={}, headers=headers).status_code == expected
    response = client_raw.post(url, json=body, headers=headers)
    assert response.status_code == expected, response.text


@pytest.mark.parametrize("field,value", [("rate", "0"), ("rate", "-1"), ("rate", "NaN"), ("rate", "1.001"),
    ("rate", "10000000000"), ("confirm_execution_evidence", False), ("confirm_execution_evidence", "true"),
    ("amount", "1"), ("agreement_reference", " "), ("execution_evidence", "short")])
def test_rejects_invalid_or_client_computed_terms(case, db_session, client_admin_real_uow, field, value):
    _, url, _ = missing(case, db_session, "ADDON")
    body = proposal_body(client_admin_real_uow, url)
    assert client_admin_real_uow.post(url, json={**body, field: value}).status_code == 422
    assert db_session.query(WorkPriceProposalORM).filter_by(company_id=case.company).count() == 0


def test_valid_later_list_does_not_change_proposal_or_approve_it(case, db_session, client_admin_real_uow):
    _, url, first = missing(case, db_session, "ADDON")
    body = proposal_body(client_admin_real_uow, url)
    activate(case, expected=1, previous=first.id)
    response = client_admin_real_uow.post(url, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["scope"]["missing_price"]["price_list_id"] == str(first.id)
    assert response.json()["status"] == "PREPARED"
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


def test_time_correction_is_separate_and_original_is_retained(case, db_session, client_admin_real_uow):
    row, url, _ = missing(case, db_session)
    at = row.client_happened_at
    row.client_happened_at, row.client_time_has_timezone = None, None
    db_session.commit()
    assert client_admin_real_uow.post(url + "/review", json={}).status_code == 409
    correction = {"performed_at": at.isoformat(), "evidence_reference": "Verified site work log QA-100"}
    body = proposal_body(client_admin_real_uow, url, execution_correction=correction)
    response = client_admin_real_uow.post(url, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["scope"]["execution_correction"]["evidence_reference"] == correction["evidence_reference"]
    db_session.refresh(row)
    assert row.client_happened_at is row.client_time_has_timezone is None


def test_foreign_company_cannot_read_or_prepare(case, db_session, client_admin_real_uow):
    from app.api.v1.deps import CurrentUser, require_admin
    _, url, _ = missing(case, db_session)
    body = proposal_body(client_admin_real_uow, url)
    client_admin_real_uow.app.dependency_overrides[require_admin] = lambda: CurrentUser(
        id=case.actor, company_id=uuid4(), role="ADMIN")
    assert client_admin_real_uow.post(url + "/review", json={}).status_code in (403, 404)
    assert client_admin_real_uow.post(url, json=body).status_code in (403, 404)


def test_audit_failure_rolls_back_proposal(case, db_session, client_admin_real_uow, monkeypatch):
    row, url, _ = missing(case, db_session)
    body = CreateWorkPriceProposal(**proposal_body(client_admin_real_uow, url))
    def fail(*args, **kwargs):
        raise RuntimeError("Audit unavailable")
    monkeypatch.setattr(AuditService, "add", fail)
    with pytest.raises(RuntimeError, match="Audit unavailable"), SqlAlchemyUnitOfWork() as uow:
        WorkPriceProposalService.create(uow, company_id=case.company, actor_user_id=case.actor,
            source="sync_queue", item_id=row.id, body=body)
    assert db_session.query(WorkPriceProposalORM).filter_by(company_id=case.company).count() == 0


def test_concurrent_retries_create_one_proposal(case, db_session, client_admin_real_uow):
    row, url, _ = missing(case, db_session, "ADDON")
    body = CreateWorkPriceProposal(**proposal_body(client_admin_real_uow, url))
    company, actor, item = case.company, case.actor, row.id
    gate = Barrier(2)
    def create():
        gate.wait(timeout=15)
        with SqlAlchemyUnitOfWork() as uow:
            return WorkPriceProposalService.create(uow, company_id=company, actor_user_id=actor,
                source="sync_queue", item_id=item, body=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(create), pool.submit(create)
        assert a.result(timeout=60) == b.result(timeout=60)
    assert db_session.query(WorkPriceProposalORM).filter_by(company_id=case.company).count() == 1


def test_nonempty_proposal_migration_cannot_be_downgraded(case, db_session, client_admin_real_uow, monkeypatch):
    import runpy
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    _, url, _ = missing(case, db_session)
    assert client_admin_real_uow.post(url, json=proposal_body(client_admin_real_uow, url)).status_code == 200
    downgrade = runpy.run_path("alembic/versions/0072_work_price_proposals.py")["downgrade"]
    monkeypatch.setitem(downgrade.__globals__, "op", Operations(MigrationContext.configure(db_session.connection())))
    with pytest.raises(RuntimeError, match="retained work price proposals exist"):
        downgrade()
    db_session.rollback()
