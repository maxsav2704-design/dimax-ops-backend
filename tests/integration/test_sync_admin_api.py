from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.identity.domain.enums import UserRole
from app.modules.sync.domain.enums import SyncEventType
from app.modules.sync.infrastructure.models import SyncEventORM, SyncQueueItemORM


def test_sync_admin_states_and_stats_return_payload(client_admin_real_uow):
    states_resp = client_admin_real_uow.get("/api/v1/admin/sync/states")
    assert states_resp.status_code == 200, states_resp.text
    assert isinstance(states_resp.json(), list)

    stats_resp = client_admin_real_uow.get("/api/v1/admin/sync/stats")
    assert stats_resp.status_code == 200, stats_resp.text
    body = stats_resp.json()
    assert "total_installers" in body
    assert "active_last_30_days" in body


def test_sync_admin_problems_returns_failed_events_and_queue_items(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_user,
):
    user = make_user(role=UserRole.INSTALLER, is_active=True)
    installer = make_installer(
        full_name="Problem Sync Installer",
        phone="+972501110001",
    )
    installer.user_id = user.id
    now = datetime.now(timezone.utc)
    queue_project_id = uuid.uuid4()
    db_session.add_all(
        [
            SyncEventORM(
                company_id=company_id,
                installer_id=installer.id,
                project_id=uuid.uuid4(),
                event_type=SyncEventType.DOOR_SET_STATUS,
                client_event_id="admin-problems-event",
                client_happened_at=now,
                payload={"door_id": str(uuid.uuid4()), "status": "INSTALLED"},
                applied_at=now,
                apply_error="Door is not assigned to this installer",
            ),
            SyncQueueItemORM(
                company_id=company_id,
                user_id=user.id,
                device_id="problem-device",
                project_id=queue_project_id,
                entity_type="door",
                entity_id=uuid.uuid4(),
                operation_type="DOOR_SET_STATUS",
                payload={"status": "INSTALLED"},
                base_version=5,
                status="CONFLICT",
                conflict_code="CONFLICT_INVALID_TRANSITION",
                created_at=now,
            ),
            SyncQueueItemORM(
                company_id=company_id,
                user_id=user.id,
                device_id="older-problem-device",
                entity_type="door",
                entity_id=uuid.uuid4(),
                operation_type="DOOR_SET_STATUS",
                payload={"status": "NOT_INSTALLED"},
                base_version=4,
                status="PENDING",
                conflict_code=None,
                created_at=now - timedelta(minutes=5),
            ),
        ]
    )
    db_session.commit()

    resp = client_admin_real_uow.get(
        f"/api/v1/admin/sync/problems?installer_id={installer.id}&limit=10"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3

    sources = {item["source"] for item in body["items"]}
    assert sources == {"sync_event", "sync_queue"}

    failed_event = next(item for item in body["items"] if item["source"] == "sync_event")
    assert failed_event["installer_id"] == str(installer.id)
    assert failed_event["installer_name"] == "Problem Sync Installer"
    assert failed_event["client_event_id"] == "admin-problems-event"
    assert failed_event["event_type"] == "DOOR_SET_STATUS"
    assert failed_event["status"] == "FAILED"
    assert failed_event["error"] == "Door is not assigned to this installer"
    assert failed_event["problem_code"] == "CONFLICT_ASSIGNMENT_CHANGED"
    assert failed_event["problem_title"] == "Assignment changed"
    assert "Do not retry" in failed_event["operator_action"]
    assert failed_event["retry_allowed"] is False
    assert failed_event["manual_review_required"] is True

    queue_item = next(item for item in body["items"] if item["source"] == "sync_queue")
    assert queue_item["installer_id"] == str(installer.id)
    assert queue_item["user_id"] == str(user.id)
    assert queue_item["operation_type"] == "DOOR_SET_STATUS"
    assert queue_item["status"] == "CONFLICT"
    assert queue_item["conflict_code"] == "CONFLICT_INVALID_TRANSITION"
    assert queue_item["problem_code"] == "CONFLICT_INVALID_TRANSITION"
    assert queue_item["problem_title"] == "Door status is stale"
    assert queue_item["retry_allowed"] is False
    assert queue_item["manual_review_required"] is True
    assert queue_item["base_version"] == 5
    assert queue_item["project_id"] == str(queue_project_id)

    limited_resp = client_admin_real_uow.get(
        f"/api/v1/admin/sync/problems?installer_id={installer.id}&limit=1"
    )
    assert limited_resp.status_code == 200, limited_resp.text
    limited_body = limited_resp.json()
    assert limited_body["total"] == 3
    assert len(limited_body["items"]) == 1

    conflict_resp = client_admin_real_uow.get(
        f"/api/v1/admin/sync/problems?installer_id={installer.id}&status=conflict&limit=10"
    )
    assert conflict_resp.status_code == 200, conflict_resp.text
    conflict_body = conflict_resp.json()
    assert conflict_body["total"] == 1
    assert conflict_body["items"][0]["status"] == "CONFLICT"
    assert conflict_body["items"][0]["problem_code"] == "CONFLICT_INVALID_TRANSITION"

    failed_resp = client_admin_real_uow.get(
        f"/api/v1/admin/sync/problems?installer_id={installer.id}&status=failed&limit=10"
    )
    assert failed_resp.status_code == 200, failed_resp.text
    failed_body = failed_resp.json()
    assert failed_body["total"] == 1
    assert failed_body["items"][0]["source"] == "sync_event"

    pending_resp = client_admin_real_uow.get(
        f"/api/v1/admin/sync/problems?installer_id={installer.id}&status=pending&limit=10"
    )
    assert pending_resp.status_code == 200, pending_resp.text
    pending_body = pending_resp.json()
    assert pending_body["total"] == 1
    assert pending_body["items"][0]["status"] == "PENDING"
    assert pending_body["items"][0]["problem_code"] == "SYNC_PENDING"

    invalid_status_resp = client_admin_real_uow.get(
        f"/api/v1/admin/sync/problems?installer_id={installer.id}&status=done"
    )
    assert invalid_status_resp.status_code == 422, invalid_status_resp.text


def test_sync_admin_reset_endpoints_success(
    client_admin_real_uow,
    db_session,
    company_id,
    admin_user,
    make_user,
):
    user = make_user(role=UserRole.INSTALLER, is_active=True)

    create_installer_resp = client_admin_real_uow.post(
        "/api/v1/admin/installers",
        json={
            "full_name": "Sync Installer",
            "phone": "+10000000031",
            "status": "ACTIVE",
            "is_active": True,
            "user_id": str(user.id),
        },
    )
    assert create_installer_resp.status_code == 201, create_installer_resp.text
    installer_id = create_installer_resp.json()["id"]

    reset_new_resp = client_admin_real_uow.post(
        f"/api/v1/admin/sync/states/{user.id}/reset"
    )
    assert reset_new_resp.status_code == 200, reset_new_resp.text
    reset_new_body = reset_new_resp.json()
    assert reset_new_body["installer_id"] == installer_id
    assert reset_new_body["last_cursor_ack"] == 0
    assert reset_new_body["lag"] >= 0
    cold_resync_log = (
        db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type == "sync_state",
            AuditLogORM.entity_id == uuid.UUID(installer_id),
            AuditLogORM.action == "SYNC_STATE_RESET",
            AuditLogORM.reason == "admin_cold_resync",
        )
        .one()
    )
    assert cold_resync_log.actor_user_id == admin_user.id
    assert cold_resync_log.before["installer_id"] == installer_id
    assert cold_resync_log.before["user_id"] == str(user.id)
    assert cold_resync_log.after["installer_id"] == installer_id
    assert cold_resync_log.after["user_id"] == str(user.id)
    assert cold_resync_log.after["last_cursor_ack"] == 0

    reset_legacy_resp = client_admin_real_uow.post(
        f"/api/v1/admin/sync/reset/{installer_id}"
    )
    assert reset_legacy_resp.status_code == 200, reset_legacy_resp.text
    assert reset_legacy_resp.json() == {"status": "reset_ok"}
    legacy_log = (
        db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type == "sync_state",
            AuditLogORM.entity_id == uuid.UUID(installer_id),
            AuditLogORM.action == "SYNC_STATE_RESET",
            AuditLogORM.reason == "admin_legacy_reset",
        )
        .one()
    )
    assert legacy_log.actor_user_id == admin_user.id
    assert legacy_log.before["installer_id"] == installer_id
    assert legacy_log.after["last_cursor_ack"] == 0

    audit_report_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs?entity_type=sync_state&action=SYNC_STATE_RESET"
    )
    assert audit_report_resp.status_code == 200, audit_report_resp.text
    audit_report_body = audit_report_resp.json()
    assert audit_report_body["summary"]["total"] >= 2
    assert audit_report_body["summary"]["by_entity"]["sync_state"] >= 2
    assert audit_report_body["summary"]["by_action"]["SYNC_STATE_RESET"] >= 2
    assert all(item["entity_type"] == "sync_state" for item in audit_report_body["items"])
    assert all(item["action"] == "SYNC_STATE_RESET" for item in audit_report_body["items"])


def test_sync_admin_reset_not_found_returns_domain_error(client_admin_real_uow):
    missing_id = uuid.uuid4()

    reset_new_resp = client_admin_real_uow.post(
        f"/api/v1/admin/sync/states/{missing_id}/reset"
    )
    assert reset_new_resp.status_code == 404, reset_new_resp.text
    assert reset_new_resp.json()["error"]["code"] == "NOT_FOUND"

    reset_legacy_resp = client_admin_real_uow.post(
        f"/api/v1/admin/sync/reset/{missing_id}"
    )
    assert reset_legacy_resp.status_code == 404, reset_legacy_resp.text
    assert reset_legacy_resp.json()["error"]["code"] == "NOT_FOUND"


def test_sync_admin_endpoints_forbidden_for_installer(client_installer):
    states_resp = client_installer.get("/api/v1/admin/sync/states")
    assert states_resp.status_code == 403, states_resp.text
    assert states_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    stats_resp = client_installer.get("/api/v1/admin/sync/stats")
    assert stats_resp.status_code == 403, stats_resp.text
    assert stats_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    problems_resp = client_installer.get("/api/v1/admin/sync/problems")
    assert problems_resp.status_code == 403, problems_resp.text
    assert problems_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    reset_resp = client_installer.post(
        f"/api/v1/admin/sync/states/{uuid.uuid4()}/reset"
    )
    assert reset_resp.status_code == 403, reset_resp.text
    assert reset_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"
