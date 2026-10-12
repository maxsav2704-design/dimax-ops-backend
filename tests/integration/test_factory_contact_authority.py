from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, select, text

from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from test_factory_price_approvals_api import ADMIN, PUBLIC, approval_case, confirmation


def contact_body(contact, **changes):
    return {key: changes.get(key, contact[key]) for key in (
        "factory_name", "recipient_name", "recipient_email", "authority_reference",
    )} | {"expected_contact_id": contact["id"]}


@pytest.mark.parametrize("scope", ["OPERATIONS", "FINANCE", "VIEWER"])
def test_only_owner_can_register_even_when_route_dependency_is_overridden(
    client, approval_case, db_session, admin_user, scope,
):
    contact = client.get(f"{ADMIN}/factory/contact").json()
    db_session.execute(text("UPDATE admin_profiles SET admin_scope=:scope WHERE user_id=:uid"),
                       {"scope": scope, "uid": admin_user.id})
    db_session.commit()
    response = client.post(f"{ADMIN}/factory/contact", json=contact_body(contact, recipient_email="other@example.com"))
    assert response.status_code == 403, response.text
    revoked = client.post(f"{ADMIN}/factory/contact/revoke", json={
        "expected_contact_id": contact["id"], "reason": "Unauthorized revocation attempt"})
    assert revoked.status_code == 403, revoked.text
    assert client.get(f"{ADMIN}/factory/contact").json() == contact


@pytest.mark.parametrize("field,value", [("recipient_email", "operator@example.com"),
    ("recipient_name", "Another representative"), ("factory_name", "Another factory")])
def test_invitation_cannot_override_registered_recipient(client, approval_case, field, value):
    response = client.post(f'{ADMIN}/{approval_case["price_list"]["id"]}/approvals',
                           json={**approval_case["body"], field: value})
    assert response.status_code == 409, response.text
    assert client.post(f"{PUBLIC}/preview", json={"token": approval_case["token"]}).status_code == 200


def test_operations_can_invite_registered_contact(client, approval_case, db_session, admin_user):
    db_session.execute(text("UPDATE admin_profiles SET admin_scope='OPERATIONS' WHERE user_id=:uid"), {"uid": admin_user.id})
    db_session.commit()
    result = client.post(f'{ADMIN}/{approval_case["price_list"]["id"]}/approvals', json=approval_case["body"])
    assert result.status_code == 200, result.text


def test_replacement_invalidates_old_link_and_stale_edits(client, client_raw, approval_case):
    old = client.get(f"{ADMIN}/factory/contact").json()
    request = contact_body(old, recipient_email="replacement@example.com")
    changed = client.post(f"{ADMIN}/factory/contact", json=request)
    assert changed.status_code == 200, changed.text
    assert changed.json()["id"] != old["id"]
    assert client.post(f"{ADMIN}/factory/contact", json=request).json() == changed.json()
    assert client_raw.post(f"{PUBLIC}/preview", json={"token": approval_case["token"]}).status_code == 404
    assert client.post(f"{ADMIN}/factory/contact", json=contact_body(old, recipient_email="stale@example.com")).status_code == 409
    assert client.post(f"{ADMIN}/factory/contact", json={**request, "expected_contact_id": str(uuid4()),
        "recipient_email": "foreign@example.com"}).status_code == 409
    assert client.post(f"{ADMIN}/factory/contact/revoke", json={"expected_contact_id": old["id"],
        "reason": "Stale revocation attempt"}).status_code == 409


def test_owner_can_revoke_authority_without_naming_a_replacement(client, client_raw, approval_case):
    contact = client.get(f"{ADMIN}/factory/contact").json()
    body = {"expected_contact_id": contact["id"], "reason": "Representative left the factory"}
    for _ in range(2):
        assert client.post(f"{ADMIN}/factory/contact/revoke", json=body).status_code == 200
    assert client.get(f"{ADMIN}/factory/contact").json() is None
    assert client_raw.post(f"{PUBLIC}/preview", json={"token": approval_case["token"]}).status_code == 404
    assert client.post(f'{ADMIN}/{approval_case["price_list"]["id"]}/approvals', json=approval_case["body"]).status_code == 409


def test_external_decision_is_audited_once_and_survives_contact_change(client, client_raw, approval_case, db_session):
    body = confirmation(client_raw, approval_case)
    contact = client.get(f"{ADMIN}/factory/contact").json()
    for _ in range(2):
        result = client_raw.post(f"{PUBLIC}/confirm", json=body, headers={"User-Agent": "QA representative"})
        assert result.status_code == 200, result.text
    rows = db_session.scalars(select(AuditLogORM).where(
        AuditLogORM.entity_id == UUID(approval_case["issued"]["invitation"]["id"]), AuditLogORM.action == "CONFIRM",
    )).all()
    assert len(rows) == 1 and rows[0].actor_user_id is None
    assert rows[0].after["factory_contact_id"] == contact["id"]
    assert rows[0].after["actor_kind"] == "FACTORY_REPRESENTATIVE"
    assert rows[0].after["snapshot_hash"] == body["snapshot_hash"]
    assert rows[0].ip == "testclient" and rows[0].user_agent == "QA representative"
    assert body["token"] not in str(rows[0].__dict__)
    assert body["verification_code"] not in str(rows[0].__dict__)
    assert client.post(f"{ADMIN}/factory/contact", json=contact_body(contact, recipient_email="new@example.com")).status_code == 200
    assert client_raw.post(f"{PUBLIC}/preview", json={"token": body["token"]}).json()["status"] == "CONFIRMED"


def test_pre_migration_pending_link_has_no_fabricated_authority(client_raw, approval_case, db_session):
    row = db_session.get(FactoryPriceApprovalORM, UUID(approval_case["issued"]["invitation"]["id"]))
    row.factory_contact_id = None
    db_session.commit()
    assert client_raw.post(f"{PUBLIC}/preview", json={"token": approval_case["token"]}).status_code == 404


def test_contact_schema_is_registered_and_downgrade_preserves_authority(db_session, company_id, admin_user):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.modules.rates.infrastructure.contact_models import FactoryContactORM

    inspector = inspect(db_session.get_bind())
    checks = {row["name"] for row in inspector.get_check_constraints("factory_contacts")}
    assert {"ck_factory_contacts_identity", "ck_factory_contacts_revocation"} <= checks
    assert any(row["name"] == "fk_factory_approvals_contact"
               for row in inspector.get_foreign_keys("factory_price_approvals"))
    contact = FactoryContactORM(company_id=company_id, approved_by=admin_user.id, factory_name="QA Factory",
        recipient_name="QA Representative", recipient_email="qa@example.com", authority_reference="QA agreement")
    db_session.add(contact)
    db_session.commit()
    migration_path = Path(__file__).resolve().parents[2] / "alembic/versions/0070_factory_contact.py"
    spec = importlib.util.spec_from_file_location("factory_contact_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with Operations.context(MigrationContext.configure(db_session.connection())):
            with pytest.raises(RuntimeError, match="Cannot discard"):
                migration.downgrade()
    finally:
        db_session.rollback()
    assert db_session.get(FactoryContactORM, contact.id) is not None


def test_unregistered_company_cannot_invite(client, make_door_type):
    door = make_door_type()
    draft = client.post(ADMIN, json={"request_id": str(uuid4()), "expected_latest_version": 0,
        "reason": "Factory offer", "agreement_reference": "QA agreement",
        "items": [{"kind": "DOOR", "target_id": str(door.id), "installer_price": "250.00"}]}).json()
    assert client.get(f"{ADMIN}/factory/contact").json() is None
    response = client.post(f'{ADMIN}/{draft["id"]}/approvals', json={
        "factory_name": "Unverified factory", "recipient_name": "Unverified representative", "recipient_email": "arbitrary@example.com"})
    assert response.status_code == 409, response.text
