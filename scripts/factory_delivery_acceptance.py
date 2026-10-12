"""Real HTTP/SMTP acceptance driver; only an explicitly isolated throwaway DB."""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.security.password import hash_password
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM, UserORM
from app.shared.infrastructure.db.model_registry import import_all_orm_models
from app.shared.infrastructure.db.session import SessionLocal

STATE = Path("/tmp/dimax-factory-delivery-state.json")
ADMIN = "/api/v1/admin/price-lists"
PUBLIC = "/api/v1/public/price-approvals"
API = "http://127.0.0.1:8000"
MAIL = "http://mailpit:8025/api/v1"


def guard() -> None:
    url = make_url(settings.DATABASE_URL)
    if not (os.getenv("DIMAX_FACTORY_DELIVERY_CHECK") == "1" and os.getenv("APP_ENV") == "test"
            and url.host == "db" and re.fullmatch(r"dimax_factory_delivery_[a-f0-9]{12}", url.database or "")
            and settings.EMAIL_ENABLED and settings.SMTP_HOST == "mailpit" and settings.SMTP_PORT == 1025
            and not settings.WHATSAPP_ENABLED and settings.PUBLIC_APP_BASE_URL == "https://factory.example.test"):
        raise RuntimeError("Requires a disposable factory-delivery database and local Mailpit")


def request(base, path, body=None, *, token=None, method=None, expected=200, response_json=True):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(base + path, data=None if body is None else json.dumps(body).encode(), headers=headers,
                  method=method or ("GET" if body is None else "POST"))
    try:
        with urlopen(req, timeout=30) as response:
            status, raw = response.status, response.read()
    except HTTPError as error:
        status, raw = error.code, error.read()
    except (URLError, TimeoutError):
        raise RuntimeError("Acceptance service unavailable") from None
    if status != expected:
        # Never print response bodies, auth headers, invitation links or codes.
        raise RuntimeError(f"Unexpected HTTP status {status} on {path.split('?')[0]}")
    return json.loads(raw) if raw and response_json else None


def save(state):
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf8") as stream:
        json.dump(state, stream)


def read_state():
    state = json.loads(STATE.read_text())
    if state["recipient"] != recipient():
        raise RuntimeError("Unexpected acceptance recipient")
    return state


def recipient():
    return f'factory-delivery-{make_url(settings.DATABASE_URL).database.removeprefix("dimax_factory_delivery_")}@example.com'


def mailbox(state):
    return [m for m in request(MAIL, "/messages?limit=200")["messages"]
            if any(r["Address"] == state["recipient"] for r in m["To"])]


def wait_message(state, *, code=False):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        matches = [m for m in mailbox(state) if ("confirmation code" in m["Subject"]) == code]
        if matches:
            assert len(matches) == 1, "Unexpected duplicate SMTP delivery"
            return request(MAIL, f'/message/{matches[0]["ID"]}')
        time.sleep(1)
    raise RuntimeError("Timed out waiting for captured factory mail")


def prepare():
    import_all_orm_models()
    with SessionLocal() as session:
        assert session.execute(text("SELECT count(*) FROM companies")).scalar_one() == 0
        cid, uid, did = uuid4(), uuid4(), uuid4()
        password = secrets.token_urlsafe(24)
        email = f"admin-{cid.hex}@example.com"
        session.add(CompanyORM(id=cid, name="Disposable factory delivery QA", is_active=True))
        session.flush()
        session.add(UserORM(id=uid, company_id=cid, email=email, full_name="QA Owner", role="ADMIN",
                            password_hash=hash_password(password), is_active=True, status="ACTIVE"))
        session.flush()
        session.add(AdminProfileORM(company_id=cid, user_id=uid, admin_scope="OWNER", can_view_rates=True))
        session.add(DoorTypeORM(id=did, company_id=cid, code="QA-ENTRY", name="QA Entrance", is_active=True))
        session.commit()
    auth = request(API, "/api/v1/auth/login", {"company_id": str(cid), "email": email,
                   "password": password, "device_id": "factory-delivery-acceptance"})["access_token"]
    state = {"auth": auth, "recipient": recipient()}
    save(state)
    contact = request(API, ADMIN + "/factory/contact", {
        "expected_contact_id": None, "factory_name": "QA Factory",
        "recipient_name": "QA Representative", "recipient_email": state["recipient"],
        "authority_reference": "Isolated acceptance: OWNER-verified QA representative",
    }, token=auth)
    state["contact_id"] = contact["id"]
    price = request(API, ADMIN, {"request_id": str(uuid4()), "expected_latest_version": 0,
                    "reason": "Isolated delivery acceptance", "agreement_reference": "QA only",
                    "items": [{"kind": "DOOR", "target_id": str(did), "installer_price": "250.00"}]}, token=auth)
    issued = request(API, f'{ADMIN}/{price["id"]}/approvals', {"factory_name": "QA Factory",
                     "recipient_name": "QA Representative", "recipient_email": state["recipient"],
                     "expires_in_hours": 24, "send_email": True}, token=auth)
    # Do not take the link from the API response: subsequent steps must receive it over SMTP.
    assert issued["email_outbox_id"]
    state["price_id"] = price["id"]
    save(state)
    with SessionLocal() as session:
        assert session.execute(text("SELECT status::text FROM outbox_messages")).scalar_one() == "PENDING"


def receive_invitation():
    state = read_state()
    message = wait_message(state)
    match = re.search(r"https://factory\.example\.test/price-approval#([A-Za-z0-9_-]{43})", message["Text"])
    assert match, "Captured invitation must contain the review link"
    assert match[0] in message["HTML"]
    state["token"] = match[1]
    save(state)
    view = request(API, PUBLIC + "/preview", {"token": state["token"]})
    assert view["status"] == "PENDING" and view["affects_earnings"] is False
    assert view["items"][0]["installer_price"] == "250.00"


def request_code():
    state = read_state()
    result = request(API, PUBLIC + "/request-code", {"token": state["token"]})
    assert result["status"] == "QUEUED"
    with SessionLocal() as session:
        assert session.execute(text("SELECT count(*) FROM outbox_messages WHERE status='PENDING'")).scalar_one() == 1


def confirm():
    state = read_state()
    message = wait_message(state, code=True)
    match = re.search(r"Confirmation code: ([0-9]{6})", message["Text"])
    assert match and match[1] in message["HTML"]
    assert state["token"] not in message["Text"] + message["HTML"]
    view = request(API, PUBLIC + "/preview", {"token": state["token"]})
    body = {"token": state["token"], "expected_version": view["version"], "snapshot_hash": view["snapshot_hash"],
            "signer_name": "QA Representative", "accepted": True}
    request(API, PUBLIC + "/confirm", body, expected=403)
    body["verification_code"] = match[1]
    signed = request(API, PUBLIC + "/confirm", body)
    assert signed["status"] == "CONFIRMED" and signed["mailbox_verified_at"]
    assert request(API, PUBLIC + "/confirm", body) == signed
    price = request(API, f'{ADMIN}/{state["price_id"]}', token=state["auth"])
    assert price["status"] == "CONFIRMED"
    with SessionLocal() as session:
        assert session.execute(text("SELECT count(*) FROM factory_price_activations")).scalar_one() == 0
        assert session.execute(text("SELECT count(*) FROM completed_work")).scalar_one() == 0
        decision = session.execute(text(
            "SELECT actor_user_id, after FROM audit_logs "
            "WHERE entity_type='FACTORY_PRICE_APPROVAL' AND action='CONFIRM'"
        )).one()
        assert decision.actor_user_id is None
        assert decision.after["factory_contact_id"] == state["contact_id"]
        assert decision.after["actor_kind"] == "FACTORY_REPRESENTATIVE"
        rows = session.execute(text("SELECT status::text, payload FROM outbox_messages")).all()
        assert len(rows) == 2 and all(row[0] == "SENT" for row in rows)
        for _, payload in rows:
            assert state["token"] not in json.dumps(payload)
        code_payload = next(payload for _, payload in rows if payload["kind"] == "FACTORY_PRICE_MAILBOX_CODE")
        assert match[1] not in json.dumps(code_payload)
    assert len(mailbox(state)) == 2


def cleanup():
    state = {"recipient": recipient()}
    messages = mailbox(state)
    if messages:
        request(MAIL, "/messages", {"IDs": [m["ID"] for m in messages]}, method="DELETE", response_json=False)
    assert not mailbox(state), "Acceptance messages were not removed"
    STATE.unlink(missing_ok=True)


def main():
    guard()
    phases = {"prepare": prepare, "invitation": receive_invitation, "request-code": request_code,
              "confirm": confirm, "cleanup": cleanup}
    if len(sys.argv) != 2 or sys.argv[1] not in phases:
        raise RuntimeError("Select an acceptance phase")
    phases[sys.argv[1]]()
    print(f"PASS: factory delivery {sys.argv[1]}")


if __name__ == "__main__":
    main()
