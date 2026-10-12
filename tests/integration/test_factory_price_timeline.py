from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import ValidationError as SchemaError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM, UserORM
from app.modules.rates.application.approval_dto import ConfirmApproval, IssueApproval
from app.modules.rates.application.approval_service import FactoryPriceApprovalService
from app.modules.rates.application.contact_dto import RegisterFactoryContact
from app.modules.rates.application.contact_service import FactoryContactService
from app.modules.rates.application.price_list_dto import CreatePriceList
from app.modules.rates.application.price_lists_service import FactoryPriceListsService
from app.modules.rates.application.timeline_dto import ActivatePriceVersion
from app.modules.rates.application.timeline_service import FactoryPriceTimelineService as Timeline
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.modules.rates.infrastructure.timeline_models import FactoryPriceActivationORM
from app.shared.domain.errors import Conflict, Forbidden, NotFound, ValidationError
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from factory_mailbox_helpers import TEST_CODE, mailbox_settings


def confirmed(company_id, actor, items, expected=0, *, confirm=True):
    with SqlAlchemyUnitOfWork() as uow:
        version = FactoryPriceListsService.create(uow, company_id=company_id, actor_user_id=actor,
            body=CreatePriceList(request_id=uuid4(), expected_latest_version=expected, reason="QA factory offer",
                                 agreement_reference="QA agreement", items=items))
    if confirm:
        with SqlAlchemyUnitOfWork() as uow:
            FactoryContactService.register(uow, company_id=company_id, actor_user_id=actor,
                body=RegisterFactoryContact(expected_contact_id=None, factory_name="QA Factory",
                    recipient_name="QA Representative", recipient_email="qa@example.com",
                    authority_reference="QA verified factory authorization"))
            issued = FactoryPriceApprovalService.issue(uow, company_id=company_id, actor_user_id=actor,
                price_list_id=version.id, body=IssueApproval(factory_name="QA Factory",
                    recipient_name="QA Representative", recipient_email="qa@example.com"))
        with mailbox_settings(), SqlAlchemyUnitOfWork() as uow:
            token = issued.confirmation_url.split("#")[1]
            preview = FactoryPriceApprovalService.preview(uow, token=token)
            FactoryPriceApprovalService.request_code(uow, token=token)
            FactoryPriceApprovalService.confirm(uow, body=ConfirmApproval(token=token,
                expected_version=version.version, snapshot_hash=preview.snapshot_hash,
                signer_name="QA Representative", accepted=True, verification_code=TEST_CODE))
    return version


def transition(company_id, actor, version, previous=None, body=None):
    body = body or ActivatePriceVersion(request_id=uuid4(), expected_active_price_list_id=previous,
                                       reason="QA reviewed transition", reviewed_transition=True)
    with SqlAlchemyUnitOfWork() as uow:
        return Timeline.activate(uow, company_id=company_id, actor_user_id=actor, price_list_id=version.id, body=body)


def quote(company_id, target, at, **kwargs):
    with SqlAlchemyUnitOfWork() as uow:
        return Timeline.quote(uow, company_id=company_id, target_id=target, performed_at=at,
                              kind=kwargs.pop("kind", "DOOR"), **kwargs)


@pytest.fixture()
def book(company_id, admin_user, make_door_type, db_session):
    door = make_door_type(name="Entrance")
    addon = AddonTypeORM(company_id=company_id, name="Adjustment", unit="pcs")
    db_session.add(addon)
    db_session.commit()
    items = [{"kind": "DOOR", "target_id": door.id, "installer_price": "250.00"},
             {"kind": "ADDON", "target_id": addon.id, "installer_price": "9.00"}]
    return door, addon, items, confirmed(company_id, admin_user.id, items)


def test_confirmation_does_not_automatically_activate(book, company_id):
    door, _, _, version = book
    assert quote(company_id, door.id, utcnow()) is None
    with pytest.raises(Conflict, match="No effective"):
        quote(company_id, door.id, utcnow(), seen_price_list_id=version.id)


def test_execution_time_selects_confirmed_price_not_upload_price(book, company_id, admin_user):
    door, addon, items, v1 = book
    a1 = transition(company_id, admin_user.id, v1)
    # Use persisted boundaries, not a second wall-clock sample that can move under VM time correction.
    old_execution = a1.effective_from
    v2 = confirmed(company_id, admin_user.id, [{**i, "installer_price": "300" if i["kind"] == "DOOR" else "12"}
                                            for i in items], 1)
    assert quote(company_id, door.id, utcnow()).rate == Decimal("250")
    a2 = transition(company_id, admin_user.id, v2, v1.id)
    assert a1.effective_from < a2.effective_from
    assert quote(company_id, door.id, old_execution, seen_price_list_id=v1.id).rate == Decimal("250")
    assert quote(company_id, door.id, old_execution.astimezone(timezone(timedelta(hours=3)))).performed_at == old_execution
    assert quote(company_id, door.id, a2.effective_from, seen_price_list_id=v2.id).rate == Decimal("300")
    assert quote(company_id, door.id, a2.effective_from - timedelta(microseconds=1)).activation_id == a1.id
    assert quote(company_id, addon.id, old_execution, kind="ADDON").amount(Decimal("1.50")) == Decimal("13.50")
    assert quote(company_id, addon.id, a2.effective_from, kind="ADDON").amount(Decimal("1.50")) == Decimal("18.00")
    with pytest.raises(Conflict, match="Cached price"):
        quote(company_id, door.id, a2.effective_from, seen_price_list_id=v1.id)


def test_first_confirmed_is_not_necessarily_first_activated(book, company_id, admin_user):
    door, _, items, v1 = book
    old_execution = utcnow() - timedelta(days=3)
    v2 = confirmed(company_id, admin_user.id, [{**i, "installer_price": "400"} for i in items], 1)
    transition(company_id, admin_user.id, v2)
    price = quote(company_id, door.id, old_execution, legacy_queue=True)
    assert price.selection == "FIRST_CONFIRMED_LEGACY" and price.price_list_id == v1.id
    assert price.rate == Decimal("250")
    assert quote(company_id, door.id, utcnow()).rate == Decimal("400")
    assert quote(company_id, door.id, utcnow(), legacy_queue=True).rate == Decimal("400")
    with pytest.raises(Conflict, match="not effective"):
        quote(company_id, door.id, old_execution, seen_price_list_id=v1.id)
    with pytest.raises(Conflict, match="explicit legacy-queue"):
        quote(company_id, door.id, old_execution)


@pytest.mark.parametrize("damage", ["missing_receipt", "wrong_status"])
def test_damaged_first_confirmation_cannot_select_later_amendment(book, company_id, admin_user, db_session, damage):
    v2 = confirmed(company_id, admin_user.id, [{**i, "installer_price": "400"} for i in book[2]], 1)
    transition(company_id, admin_user.id, v2)
    if damage == "missing_receipt":
        db_session.execute(text("DELETE FROM factory_price_approvals WHERE price_list_id=:pid"), {"pid": book[3].id})
    else:
        db_session.execute(text("UPDATE factory_price_lists SET status='DRAFT' WHERE id=:pid"), {"pid": book[3].id})
    db_session.commit()
    with pytest.raises(Conflict, match="confirmation no longer matches"):
        quote(company_id, book[0].id, utcnow() - timedelta(days=1), legacy_queue=True)


def test_missing_first_price_does_not_fall_forward(book, company_id, admin_user, make_door_type):
    _, _, items, _ = book
    new_type = make_door_type(name="Later fire door")
    v2 = confirmed(company_id, admin_user.id, items + [
        {"kind": "DOOR", "target_id": new_type.id, "installer_price": "500"}], 1)
    transition(company_id, admin_user.id, v2)
    with pytest.raises(Conflict) as error:
        quote(company_id, new_type.id, utcnow() - timedelta(days=1), legacy_queue=True)
    assert error.value.meta == {"reason": "MISSING_FACTORY_PRICE"}
    assert quote(company_id, new_type.id, utcnow()).rate == Decimal("500")


@pytest.mark.parametrize("mode", ["FINANCE", "VIEWER", "no_rates", "inactive", "no_profile", "INSTALLER", "foreign", "inactive_company"])
def test_only_authorized_active_company_admin_can_activate(book, company_id, admin_user, db_session, make_user, mode):
    version = book[3]
    actor = admin_user.id
    profile = db_session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == actor))
    if mode in ("FINANCE", "VIEWER"):
        profile.admin_scope = mode
    elif mode == "no_rates":
        profile.can_view_rates = False
    elif mode == "inactive":
        db_session.get(UserORM, actor).is_active = False
    elif mode == "inactive_company":
        db_session.get(CompanyORM, company_id).is_active = False
    elif mode == "no_profile":
        db_session.delete(profile)
    elif mode == "INSTALLER":
        actor = make_user().id
    else:
        actor = uuid4()
    db_session.commit()
    with pytest.raises(Forbidden):
        transition(company_id, actor, version)
    assert db_session.scalar(select(FactoryPriceActivationORM).where(FactoryPriceActivationORM.company_id == company_id)) is None


def test_operations_scope_can_activate(book, company_id, admin_user, db_session):
    db_session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == admin_user.id)).admin_scope = "OPERATIONS"
    db_session.commit()
    assert transition(company_id, admin_user.id, book[3]).price_list_id == book[3].id


def test_retries_do_not_reapply_or_accept_changed_payload(book, company_id, admin_user):
    _, _, items, v1 = book
    body = ActivatePriceVersion(request_id=uuid4(), expected_active_price_list_id=None, reason="QA reviewed", reviewed_transition=True)
    original = transition(company_id, admin_user.id, v1, body=body)
    v2 = confirmed(company_id, admin_user.id, items, 1)
    transition(company_id, admin_user.id, v2, v1.id)
    assert transition(company_id, admin_user.id, v1, body=body) == original
    with pytest.raises(Conflict, match="another price transition"):
        transition(company_id, admin_user.id, v2, body=body)
    with pytest.raises(Conflict, match="Active price version changed"):
        transition(company_id, admin_user.id, v2)
    with pytest.raises(Conflict, match="older version"):
        transition(company_id, admin_user.id, v1, v2.id)


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_transitions_are_serialized(book, company_id, admin_user, same_request):
    barrier = Barrier(2)
    bodies = [ActivatePriceVersion(request_id=uuid4(), expected_active_price_list_id=None,
                                  reason="QA reviewed", reviewed_transition=True) for _ in range(2)]
    if same_request:
        bodies[1] = bodies[0]
    def submit(body):
        barrier.wait(timeout=15)
        try:
            with SqlAlchemyUnitOfWork() as uow:
                uow.session.execute(text("SET LOCAL lock_timeout = '5s'"))
                return Timeline.activate(uow, company_id=company_id, actor_user_id=admin_user.id,
                                         price_list_id=book[3].id, body=body).id
        except Conflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, bodies))
    if same_request:
        assert results[0] == results[1] != "conflict"
    else:
        assert results.count("conflict") == 1


@pytest.mark.parametrize("mode", ["draft", "superseded", "missing_type", "bad_hash"])
def test_preflight_blockers_prevent_transition(book, company_id, admin_user, db_session, make_door_type, mode):
    _, _, items, version = book
    if mode == "draft":
        version = confirmed(company_id, admin_user.id, items, 1, confirm=False)
    elif mode == "superseded":
        confirmed(company_id, admin_user.id, items, 1)
    elif mode == "missing_type":
        make_door_type(name="Missing price")
    else:
        db_session.scalar(select(FactoryPriceApprovalORM).where(FactoryPriceApprovalORM.price_list_id == version.id)).snapshot_hash = "0" * 64
        db_session.commit()
    with pytest.raises(Conflict, match="blocked"):
        transition(company_id, admin_user.id, version)


def test_clock_regression_does_not_backdate_transition(book, company_id, admin_user, monkeypatch):
    first = transition(company_id, admin_user.id, book[3])
    newer = confirmed(company_id, admin_user.id, book[2], 1)
    monkeypatch.setattr("app.modules.rates.application.timeline_service.utcnow", lambda: first.effective_from)
    with pytest.raises(Conflict):
        transition(company_id, admin_user.id, newer, book[3].id)


def test_audit_failure_rolls_back_price_transition(book, company_id, admin_user, db_session, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("QA audit failure")
    monkeypatch.setattr("app.modules.rates.application.timeline_service.AuditService.add", fail)
    with pytest.raises(RuntimeError, match="audit failure"):
        transition(company_id, admin_user.id, book[3])
    assert db_session.scalar(select(FactoryPriceActivationORM).where(FactoryPriceActivationORM.company_id == company_id)) is None


@pytest.mark.parametrize("tamper", ["price", "activation_hash", "receipt_hash", "snapshot"])
def test_historical_quote_requires_unchanged_evidence(book, company_id, admin_user, db_session, tamper):
    transition(company_id, admin_user.id, book[3])
    if tamper == "price":
        db_session.execute(text("UPDATE factory_price_list_items SET installer_price=999 WHERE price_list_id=:pid"), {"pid": book[3].id})
    elif tamper == "activation_hash":
        db_session.scalar(select(FactoryPriceActivationORM).where(FactoryPriceActivationORM.company_id == company_id)).snapshot_hash = "0" * 64
    else:
        receipt = db_session.scalar(select(FactoryPriceApprovalORM).where(FactoryPriceApprovalORM.price_list_id == book[3].id))
        if tamper == "receipt_hash":
            receipt.snapshot_hash = "0" * 64
        else:
            receipt.snapshot = {}
    db_session.commit()
    with pytest.raises(Conflict):
        quote(company_id, book[0].id, utcnow())


def test_expired_link_and_catalog_rename_do_not_reprice_historical_work(book, company_id, admin_user, db_session):
    receipt = db_session.scalar(select(FactoryPriceApprovalORM).where(FactoryPriceApprovalORM.price_list_id == book[3].id))
    receipt.created_at, receipt.confirmed_at, receipt.expires_at = utcnow() - timedelta(days=3), utcnow() - timedelta(days=2), utcnow() - timedelta(days=1)
    receipt.mailbox_verified_at = receipt.confirmed_at
    receipt.mailbox_requested_at = receipt.confirmed_at - timedelta(minutes=1)
    receipt.mailbox_code_expires_at = receipt.confirmed_at + timedelta(minutes=9)
    db_session.commit()
    at = transition(company_id, admin_user.id, book[3]).effective_from
    book[1].name, book[1].unit = "New catalog name", "hour"
    db_session.commit()
    price = quote(company_id, book[1].id, at, kind="ADDON")
    assert price.unit == "pcs" and price.rate == Decimal("9")


def test_company_and_target_scope_never_fall_back_to_other_prices(book, company_id, admin_user):
    transition(company_id, admin_user.id, book[3])
    assert quote(uuid4(), book[0].id, utcnow()) is None
    with pytest.raises(Conflict, match="no price"):
        quote(company_id, uuid4(), utcnow())
    with pytest.raises(NotFound):
        transition(company_id, admin_user.id, book[3].model_copy(update={"id": uuid4()}), book[3].id)


@pytest.fixture()
def other_admin(db_session, make_user):
    cid = uuid4()
    db_session.add(CompanyORM(id=cid, name="Other QA company", is_active=True))
    db_session.commit()
    user = make_user(company=cid, role=UserRole.ADMIN)
    try:
        yield cid, user.id
    finally:
        db_session.rollback()
        db_session.execute(text("DELETE FROM users WHERE company_id=:cid"), {"cid": cid})
        db_session.execute(text("DELETE FROM companies WHERE id=:cid"), {"cid": cid})
        db_session.commit()


def test_real_foreign_admin_cannot_activate_or_read_company_price(book, company_id, admin_user, other_admin):
    cid, actor = other_admin
    transition(company_id, admin_user.id, book[3])
    with pytest.raises(Forbidden):
        transition(company_id, actor, book[3], book[3].id)
    with pytest.raises(NotFound):
        transition(cid, actor, book[3])
    assert quote(cid, book[0].id, utcnow()) is None
    with pytest.raises(Conflict, match="No effective"):
        quote(cid, book[0].id, utcnow(), seen_price_list_id=book[3].id)


@pytest.mark.parametrize("time_mode", ["naive", "future", "bad_kind"])
def test_execution_time_and_kind_are_validated(book, company_id, time_mode):
    at = utcnow() + timedelta(days=1) if time_mode == "future" else utcnow()
    if time_mode == "naive":
        at = at.replace(tzinfo=None)
    with pytest.raises(ValidationError):
        quote(company_id, book[0].id, at, kind="OTHER" if time_mode == "bad_kind" else "DOOR")


@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "Infinity", "0.001", "10000000000", "9999999999.99"])
def test_invalid_amounts_are_rejected(book, company_id, admin_user, quantity):
    transition(company_id, admin_user.id, book[3])
    price = quote(company_id, book[1].id, utcnow(), kind="ADDON")
    with pytest.raises(ValidationError):
        price.amount(Decimal(quantity))


def test_quote_is_frozen_and_door_quantity_is_one(book, company_id, admin_user):
    transition(company_id, admin_user.id, book[3])
    price = quote(company_id, book[0].id, utcnow())
    assert price.amount(Decimal("1")) == Decimal("250")
    with pytest.raises(ValidationError):
        price.amount(Decimal("2"))
    with pytest.raises(SchemaError):
        price.rate = Decimal("999")


def test_decimal_half_up_rounding(book, company_id, admin_user):
    items = [{**i, "installer_price": "9.01" if i["kind"] == "ADDON" else "250"} for i in book[2]]
    version = confirmed(company_id, admin_user.id, items, 1)
    transition(company_id, admin_user.id, version)
    price = quote(company_id, book[1].id, utcnow(), kind="ADDON")
    assert price.amount(Decimal("1.50")) == Decimal("13.52")


@pytest.mark.parametrize("extra", [{"reviewed_transition": False}, {"reviewed_transition": 1},
                                   {"effective_from": "2000-01-01"}, {"installer_price": "999"}])
def test_transition_dto_forbids_backdating_prices_and_implicit_review(extra):
    with pytest.raises(SchemaError):
        ActivatePriceVersion.model_validate({"request_id": str(uuid4()), "expected_active_price_list_id": None,
            "reason": "QA reviewed", "reviewed_transition": True, **extra})


def test_activation_is_audited_once_without_private_confirmation_link(book, company_id, admin_user, db_session):
    row = transition(company_id, admin_user.id, book[3])
    logs = db_session.scalars(select(AuditLogORM).where(AuditLogORM.company_id == company_id,
        AuditLogORM.action == "FACTORY_PRICE_VERSION_EFFECTIVE")).all()
    assert len(logs) == 1 and logs[0].after["activation_id"] == str(row.id)
    assert set(logs[0].after) == {"activation_id", "version", "approval_id", "snapshot_hash", "effective_from", "reviewed_transition"}


@pytest.mark.parametrize("mutation", ["receipt", "tenant", "request", "time", "version", "backdate"])
def test_activation_database_constraints(book, company_id, admin_user, db_session, mutation):
    active = transition(company_id, admin_user.id, book[3])
    a1 = db_session.get(FactoryPriceActivationORM, active.id)
    second = confirmed(company_id, admin_user.id, book[2], 1)
    receipt = db_session.scalar(select(FactoryPriceApprovalORM).where(FactoryPriceApprovalORM.price_list_id == second.id))
    now = utcnow()
    values = dict(company_id=company_id, price_list_id=second.id, approval_id=receipt.id, request_id=uuid4(),
        request_fingerprint="a" * 64, snapshot_hash=receipt.snapshot_hash, effective_from=now,
        created_at=now, updated_at=now, created_by=admin_user.id, reason="QA reviewed")
    constraint = {"receipt": "fk_factory_activation_tenant_approval", "tenant": "fk_factory_activation_tenant_list",
        "request": "uq_factory_activation_request", "time": "uq_factory_activation_time",
        "version": "uq_factory_activation_list", "backdate": "ck_factory_activation_time"}[mutation]
    if mutation == "receipt":
        values["approval_id"] = a1.approval_id
    elif mutation == "tenant":
        values["company_id"] = uuid4()
    elif mutation == "request":
        values["request_id"] = a1.request_id
    elif mutation == "time":
        values["effective_from"] = values["created_at"] = a1.effective_from
    elif mutation == "version":
        values["price_list_id"], values["approval_id"] = a1.price_list_id, a1.approval_id
    else:
        values["effective_from"] = now - timedelta(days=1)
    with pytest.raises(IntegrityError, match=constraint):
        with db_session.begin_nested():
            db_session.add(FactoryPriceActivationORM(**values))
            db_session.flush()
