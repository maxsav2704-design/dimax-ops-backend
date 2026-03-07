from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.modules.audit.infrastructure.models import AuditLogORM
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
        json={
            "project_id": str(project_id),
            "title": "Audit Journal",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_installers_crud_actions_write_audit_logs(client, db_session, company_id, admin_user):
    create_resp = client.post(
        "/api/v1/admin/installers",
        json={
            "full_name": "Audit Installer",
            "phone": "+10000000021",
            "status": "ACTIVE",
            "is_active": True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    installer_id = create_resp.json()["id"]

    update_resp = client.patch(
        f"/api/v1/admin/installers/{installer_id}",
        json={"full_name": "Audit Installer Updated"},
    )
    assert update_resp.status_code == 200, update_resp.text

    delete_resp = client.delete(f"/api/v1/admin/installers/{installer_id}")
    assert delete_resp.status_code == 204, delete_resp.text

    rows = (
        db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type == "installer",
            AuditLogORM.entity_id == uuid.UUID(installer_id),
            AuditLogORM.action.in_(
                ["INSTALLER_CREATE", "INSTALLER_UPDATE", "INSTALLER_DELETE"]
            ),
        )
        .all()
    )
    by_action = {row.action: row for row in rows}

    assert set(by_action) == {
        "INSTALLER_CREATE",
        "INSTALLER_UPDATE",
        "INSTALLER_DELETE",
    }

    create_log = by_action["INSTALLER_CREATE"]
    assert create_log.actor_user_id == admin_user.id
    assert create_log.before is None
    assert create_log.after["full_name"] == "Audit Installer"
    assert create_log.after["phone"] == "+10000000021"

    update_log = by_action["INSTALLER_UPDATE"]
    assert update_log.before["full_name"] == "Audit Installer"
    assert update_log.after["full_name"] == "Audit Installer Updated"

    delete_log = by_action["INSTALLER_DELETE"]
    assert delete_log.before["deleted_at"] is None
    assert delete_log.after["is_active"] is False
    assert delete_log.after["status"] == "INACTIVE"
    assert delete_log.after["deleted_at"] is not None


def test_installers_link_unlink_actions_write_audit_logs(
    client,
    db_session,
    company_id,
    admin_user,
    make_installer,
    make_user,
):
    installer = make_installer(full_name="Audit Link Installer", phone="+10000000022")
    user = make_user()

    link_resp = client.post(
        f"/api/v1/admin/installers/{installer.id}/link-user",
        json={"user_id": str(user.id)},
    )
    assert link_resp.status_code == 200, link_resp.text

    unlink_resp = client.delete(f"/api/v1/admin/installers/{installer.id}/link-user")
    assert unlink_resp.status_code == 200, unlink_resp.text

    rows = (
        db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type == "installer",
            AuditLogORM.entity_id == installer.id,
            AuditLogORM.action.in_(
                ["INSTALLER_LINK_USER", "INSTALLER_UNLINK_USER"]
            ),
        )
        .all()
    )
    by_action = {row.action: row for row in rows}

    assert set(by_action) == {"INSTALLER_LINK_USER", "INSTALLER_UNLINK_USER"}

    link_log = by_action["INSTALLER_LINK_USER"]
    assert link_log.actor_user_id == admin_user.id
    assert link_log.before["user_id"] is None
    assert link_log.after["user_id"] == str(user.id)

    unlink_log = by_action["INSTALLER_UNLINK_USER"]
    assert unlink_log.before["user_id"] == str(user.id)
    assert unlink_log.after["user_id"] is None


def test_installer_rates_crud_actions_write_audit_logs(
    client,
    db_session,
    company_id,
    admin_user,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="Audit Rate Installer", phone="+10000000023")
    door_type = make_door_type(name="Audit Rate Door")

    create_resp = client.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type.id),
            "price": "150.00",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    rate_id = create_resp.json()["id"]

    update_resp = client.patch(
        f"/api/v1/admin/installer-rates/{rate_id}",
        json={"price": "175.00"},
    )
    assert update_resp.status_code == 200, update_resp.text

    delete_resp = client.delete(f"/api/v1/admin/installer-rates/{rate_id}")
    assert delete_resp.status_code == 204, delete_resp.text

    rows = (
        db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type == "installer_rate",
            AuditLogORM.entity_id == uuid.UUID(rate_id),
            AuditLogORM.action.in_(
                [
                    "INSTALLER_RATE_CREATE",
                    "INSTALLER_RATE_UPDATE",
                    "INSTALLER_RATE_DELETE",
                ]
            ),
        )
        .all()
    )
    by_action = {row.action: row for row in rows}
    assert set(by_action) == {
        "INSTALLER_RATE_CREATE",
        "INSTALLER_RATE_UPDATE",
        "INSTALLER_RATE_DELETE",
    }

    create_log = by_action["INSTALLER_RATE_CREATE"]
    assert create_log.actor_user_id == admin_user.id
    assert create_log.before is None
    assert create_log.after["installer_id"] == str(installer.id)
    assert create_log.after["door_type_id"] == str(door_type.id)
    assert create_log.after["price"] == "150.00"

    update_log = by_action["INSTALLER_RATE_UPDATE"]
    assert update_log.before["price"] == "150.00"
    assert update_log.after["price"] == "175.00"

    delete_log = by_action["INSTALLER_RATE_DELETE"]
    assert delete_log.before["price"] == "175.00"
    assert delete_log.after is None


def test_installer_rates_bulk_actions_write_audit_logs(
    client,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="Audit Bulk Rate Installer", phone="+10000000026")
    door_type_a = make_door_type(name="Audit Bulk Rate Door A")
    door_type_b = make_door_type(name="Audit Bulk Rate Door B")

    create_a = client.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type_a.id),
            "price": "150.00",
        },
    )
    assert create_a.status_code == 201, create_a.text
    rate_a = create_a.json()["id"]

    create_b = client.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type_b.id),
            "price": "160.00",
        },
    )
    assert create_b.status_code == 201, create_b.text
    rate_b = create_b.json()["id"]
    bulk_effective_from = datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc).isoformat()

    bulk_set_resp = client.post(
        "/api/v1/admin/installer-rates/bulk",
        json={
            "ids": [rate_a, rate_b],
            "operation": "set_price",
            "price": "199.00",
            "effective_from": bulk_effective_from,
        },
    )
    assert bulk_set_resp.status_code == 200, bulk_set_resp.text
    assert bulk_set_resp.json()["affected"] == 2

    bulk_delete_resp = client.post(
        "/api/v1/admin/installer-rates/bulk",
        json={"ids": [rate_a], "operation": "delete"},
    )
    assert bulk_delete_resp.status_code == 200, bulk_delete_resp.text
    assert bulk_delete_resp.json()["affected"] == 1

    rows = (
        db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type == "installer_rate",
            AuditLogORM.action.in_(["INSTALLER_RATE_CREATE", "INSTALLER_RATE_DELETE"]),
            AuditLogORM.reason.in_(["BULK_SET_PRICE", "BULK_DELETE"]),
        )
        .all()
    )

    set_rows = [x for x in rows if x.action == "INSTALLER_RATE_CREATE" and x.reason == "BULK_SET_PRICE"]
    del_rows = [x for x in rows if x.action == "INSTALLER_RATE_DELETE" and x.reason == "BULK_DELETE"]
    assert len(set_rows) == 2
    assert len(del_rows) == 1
    assert all(x.before["price"] in {"150.00", "160.00"} for x in set_rows)
    assert all(x.after["price"] == "199.00" for x in set_rows)
    assert all(
        x.after["effective_from"] in {
            bulk_effective_from,
            bulk_effective_from.replace("+00:00", "Z"),
        }
        for x in set_rows
    )
    assert del_rows[0].before["price"] == "150.00"
    assert del_rows[0].after is None


def test_journal_send_writes_audit_log(
    client_admin_real_uow,
    db_session,
    company_id,
    admin_user,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Audit Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)

    mark_ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert mark_ready_resp.status_code == 200, mark_ready_resp.text

    send_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "email_to": "audit.client@example.com",
            "subject": "Audit Subject",
            "message": "Audit message",
            "send_email": True,
            "send_whatsapp": False,
        },
    )
    assert send_resp.status_code == 200, send_resp.text

    row = (
        db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type == "journal",
            AuditLogORM.entity_id == uuid.UUID(journal_id),
            AuditLogORM.action == "JOURNAL_SEND_REQUESTED",
        )
        .order_by(AuditLogORM.created_at.desc())
        .first()
    )
    assert row is not None
    assert row.actor_user_id == admin_user.id
    assert row.before["email_delivery_status"] == "NONE"
    assert row.before["whatsapp_delivery_status"] == "NONE"
    assert row.after["email_delivery_status"] == "PENDING"
    assert row.after["whatsapp_delivery_status"] == "NONE"
    assert row.after["enqueued"]["email"] is True
    assert row.after["enqueued"]["whatsapp"] is False
    assert row.after["outbox_ids"]["email"] is not None
