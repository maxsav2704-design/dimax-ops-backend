from __future__ import annotations

import uuid

from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


def _create_project(db_session, *, company_id: uuid.UUID, name: str) -> ProjectORM:
    row = ProjectORM(
        company_id=company_id,
        name=name,
        address=f"{name} address",
        status=ProjectStatus.OK,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _create_journal(client_admin_real_uow, *, project_id: uuid.UUID) -> str:
    resp = client_admin_real_uow.post(
        "/api/v1/admin/journals",
        json={"project_id": str(project_id), "title": "Outbox Journal"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_outbox_admin_list_and_get(client_admin_real_uow, db_session, company_id):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Outbox Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)

    ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert ready_resp.status_code == 200, ready_resp.text

    send_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "email_to": "client@example.com",
            "whatsapp_to": "+15550003333",
            "send_email": True,
            "send_whatsapp": True,
        },
    )
    assert send_resp.status_code == 200, send_resp.text

    list_resp = client_admin_real_uow.get(
        f"/api/v1/admin/outbox?journal_id={journal_id}&limit=10"
    )
    assert list_resp.status_code == 200, list_resp.text
    payload = list_resp.json()
    assert len(payload["items"]) >= 2

    first = payload["items"][0]
    assert first["status"].endswith(("PENDING", "SENT", "FAILED"))
    assert first["delivery_status"].endswith(
        ("NONE", "PENDING", "DELIVERED", "FAILED")
    )

    get_resp = client_admin_real_uow.get(f"/api/v1/admin/outbox/{first['id']}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == first["id"]


def test_outbox_admin_get_not_found(client_admin_real_uow):
    missing_id = uuid.uuid4()
    resp = client_admin_real_uow.get(f"/api/v1/admin/outbox/{missing_id}")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_outbox_admin_endpoints_forbidden_for_installer(client_installer):
    list_resp = client_installer.get("/api/v1/admin/outbox")
    assert list_resp.status_code == 403, list_resp.text
    assert list_resp.json()["error"]["code"] == "FORBIDDEN"

    get_resp = client_installer.get(f"/api/v1/admin/outbox/{uuid.uuid4()}")
    assert get_resp.status_code == 403, get_resp.text
    assert get_resp.json()["error"]["code"] == "FORBIDDEN"
