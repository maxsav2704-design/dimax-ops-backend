from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread, main_thread
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.modules.installers.api.rates_schemas import InstallerRateCreateDTO
from app.modules.installers.application.admin_api_service import InstallerRatesAdminApiService
from app.modules.rates.application.timeline_dto import ActivatePriceVersion
from app.modules.rates.application.timeline_service import FactoryPriceTimelineService as Timeline
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.modules.rates.infrastructure.price_lists_repository import FactoryPriceListsRepository
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.shared.domain.errors import Conflict
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_earnings import case, activate, confirmed, submit, earning


STATE = "/api/v1/admin/price-lists/state"
RATES = "/api/v1/admin/installer-rates"


def rate_payload(case):
    return {"installer_id": str(case.installer), "door_type_id": str(case.door_type), "price": "111.00"}


@pytest.mark.parametrize("operation", ["create", "update", "reschedule", "delete", "bulk_price", "bulk_delete"])
def test_active_factory_prices_freeze_individual_writers(case, client_admin_real_uow, db_session, operation):
    client = client_admin_real_uow
    response = client.post(RATES, json=rate_payload(case))
    assert response.status_code == 201, response.text
    original = response.json()
    version, _ = activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    work, proof = earning(db_session, case)
    old_earning = (work.id, work.rate_snapshot, work.amount_snapshot, proof.price_list_id)
    if operation == "create":
        response = client.post(RATES, json=rate_payload(case))
    elif operation in ("update", "reschedule"):
        response = client.patch(f"{RATES}/{original['id']}", json={"price": "999"} if operation == "update"
                                else {"effective_from": "2030-01-01T00:00:00Z"})
    elif operation == "delete":
        response = client.delete(f"{RATES}/{original['id']}")
    else:
        response = client.post(RATES + "/bulk", json={"ids": [original["id"], str(uuid4())],
            "operation": "set_price" if operation == "bulk_price" else "delete",
            **({"price": "999"} if operation == "bulk_price" else {})})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["meta"]["reason"] == "FACTORY_PRICES_ACTIVE"
    assert client.get(f"{RATES}/{original['id']}").json() == original
    assert len(client.get(RATES + f"?installer_id={case.installer}").json()) == 1
    work, proof = earning(db_session, case)
    assert (work.id, work.rate_snapshot, work.amount_snapshot, proof.price_list_id) == old_earning
    state = client.get(STATE)
    assert state.status_code == 200, state.text
    assert state.json()["mode"] == "FACTORY"
    assert state.json()["active_price"]["price_list_id"] == str(version.id)


def test_confirmation_without_activation_does_not_claim_effective_price(case, client_admin_real_uow):
    confirmed(case.company, case.actor, case.items)
    assert client_admin_real_uow.get(STATE).json() == {"mode": "LEGACY", "active_price": None}
    assert client_admin_real_uow.post(RATES, json=rate_payload(case)).status_code == 201


def test_later_confirmation_does_not_replace_active_display(case, client_admin_real_uow):
    version, activation = activate(case)
    confirmed(case.company, case.actor, case.items, 1)
    snapshot = client_admin_real_uow.get(STATE).json()["active_price"]
    assert snapshot["price_list_id"] == str(version.id) and snapshot["version"] == 1
    assert snapshot["effective_from"].replace("Z", "+00:00") == activation.effective_from.isoformat()


def test_damaged_confirmation_fails_closed_for_display_and_writes(case, client_admin_real_uow, db_session):
    version, _ = activate(case)
    receipt = db_session.scalar(select(FactoryPriceApprovalORM).where(FactoryPriceApprovalORM.price_list_id == version.id))
    receipt.snapshot_hash = "0" * 64
    db_session.commit()
    assert client_admin_real_uow.get(STATE).status_code == 409
    assert client_admin_real_uow.post(RATES, json=rate_payload(case)).status_code == 409


def test_rate_write_waits_for_activation_commit(case, monkeypatch, db_session):
    version = confirmed(case.company, case.actor, case.items)
    waiting = Event()
    lock = FactoryPriceListsRepository.lock_company
    def observed_lock(repo, company_id):
        if current_thread() is not main_thread():
            waiting.set()
        return lock(repo, company_id)
    monkeypatch.setattr(FactoryPriceListsRepository, "lock_company", observed_lock)
    def write():
        with pytest.raises(Conflict):
            with SqlAlchemyUnitOfWork() as uow:
                uow.session.execute(text("SET LOCAL lock_timeout = '15s'"))
                InstallerRatesAdminApiService.create_rate(uow, company_id=case.company, actor_user_id=case.actor,
                    data=InstallerRateCreateDTO(**rate_payload(case)))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with SqlAlchemyUnitOfWork() as uow:
            Timeline.activate(uow, company_id=case.company, actor_user_id=case.actor, price_list_id=version.id,
                body=ActivatePriceVersion(request_id=uuid4(), expected_active_price_list_id=None,
                    reason="Reviewed test cutover", reviewed_transition=True))
            future = pool.submit(write)
            assert waiting.wait(timeout=10)
        future.result(timeout=20)
    assert db_session.query(InstallerRateORM).filter_by(company_id=case.company).count() == 0


@pytest.mark.parametrize("scope,rates,expected", [("OWNER", True, 200), ("OPERATIONS", True, 200),
    ("FINANCE", True, 200), ("OPERATIONS", False, 403), ("VIEWER", False, 403), ("INSTALLER", False, 403)])
def test_pricing_state_uses_live_permissions(case, client_raw, make_user, db_session, scope, rates, expected):
    from app.modules.identity.domain.enums import UserRole
    from app.modules.identity.infrastructure.models import AdminProfileORM
    user = make_user(role=UserRole.INSTALLER if scope == "INSTALLER" else UserRole.ADMIN)
    if scope != "INSTALLER":
        profile = db_session.query(AdminProfileORM).filter_by(user_id=user.id).one()
        profile.admin_scope, profile.can_view_rates = scope, rates
        db_session.commit()
    assert client_raw.get(STATE).status_code == 401
    login = client_raw.post("/api/v1/auth/login", json={"company_id": str(case.company),
        "email": user.email, "password": "secret123", "device_id": "price-write-boundary"})
    assert login.status_code == 200, login.text
    response = client_raw.get(STATE, headers={"Authorization": f'Bearer {login.json()["access_token"]}'})
    assert response.status_code == expected, response.text


def test_company_state_does_not_use_another_tenants_prices(case):
    activate(case)
    with SqlAlchemyUnitOfWork() as uow:
        assert Timeline.company_state(uow, company_id=uuid4()).model_dump() == {"mode": "LEGACY", "active_price": None}
