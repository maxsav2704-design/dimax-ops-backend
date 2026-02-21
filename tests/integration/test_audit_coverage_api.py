from __future__ import annotations

import uuid

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
