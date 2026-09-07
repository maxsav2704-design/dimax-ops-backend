from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.modules.identity.domain.enums import UserRole
from app.modules.sync.application import health_service
from app.modules.sync.domain.enums import SyncEventType
from app.modules.sync.infrastructure.models import (
    InstallerSyncStateORM,
    SyncEventORM,
    SyncQueueItemORM,
)


def test_sync_admin_health_run_and_summary_payload(client_admin_real_uow):
    run_resp = client_admin_real_uow.post("/api/v1/admin/sync/health/run")
    assert run_resp.status_code == 200, run_resp.text
    run_body = run_resp.json()
    assert run_body["ok"] is True
    assert "data" in run_body
    assert "counts" in run_body["data"]

    summary_resp = client_admin_real_uow.get("/api/v1/admin/sync/health/summary")
    assert summary_resp.status_code == 200, summary_resp.text
    summary_body = summary_resp.json()
    for key in ("max_cursor", "counts", "alerts_sent", "top_laggers", "top_offline"):
        assert key in summary_body


def test_sync_admin_health_includes_installer_contact_context(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
):
    installer = make_installer(
        full_name="Sync Monitor Installer",
        phone="+972501112233",
    )
    db_session.add(
        InstallerSyncStateORM(
            company_id=company_id,
            installer_id=installer.id,
            last_cursor_ack=0,
            last_seen_at=None,
        )
    )
    db_session.commit()

    summary_resp = client_admin_real_uow.get("/api/v1/admin/sync/health/summary")
    assert summary_resp.status_code == 200, summary_resp.text
    summary_body = summary_resp.json()
    item = summary_body["top_offline"][0]
    assert item["installer_id"] == str(installer.id)
    assert item["installer_name"] == "Sync Monitor Installer"
    assert item["installer_phone"] == "+972501112233"


def test_sync_admin_health_includes_failed_events_and_queue_problems(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_user,
):
    user = make_user(role=UserRole.INSTALLER, is_active=True)
    installer = make_installer(
        full_name="Sync Problem Installer",
        phone="+972501119999",
    )
    installer.user_id = user.id
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            InstallerSyncStateORM(
                company_id=company_id,
                installer_id=installer.id,
                last_cursor_ack=0,
                last_seen_at=now,
            ),
            SyncEventORM(
                company_id=company_id,
                installer_id=installer.id,
                project_id=uuid.uuid4(),
                event_type=SyncEventType.DOOR_SET_STATUS,
                client_event_id="admin-health-failed-event",
                client_happened_at=now,
                payload={"door_id": str(uuid.uuid4())},
                applied_at=now,
                apply_error="Door is not assigned to this installer",
            ),
            SyncQueueItemORM(
                company_id=company_id,
                user_id=user.id,
                device_id="health-device",
                entity_type="door",
                entity_id=uuid.uuid4(),
                operation_type="DOOR_SET_STATUS",
                payload={"status": "INSTALLED"},
                base_version=0,
                status="CONFLICT",
                conflict_code="CONFLICT_ASSIGNMENT_CHANGED",
                created_at=now,
            ),
            SyncQueueItemORM(
                company_id=company_id,
                user_id=user.id,
                device_id="health-device",
                entity_type="door",
                entity_id=uuid.uuid4(),
                operation_type="DOOR_SET_STATUS",
                payload={"status": "INSTALLED"},
                base_version=0,
                status="AUTH_REQUIRED",
                conflict_code=None,
                created_at=now,
            ),
        ]
    )
    db_session.commit()

    summary_resp = client_admin_real_uow.get("/api/v1/admin/sync/health/summary")
    assert summary_resp.status_code == 200, summary_resp.text
    summary_body = summary_resp.json()

    counts = summary_body["counts"]
    assert counts["failed_events"] == 1
    assert counts["queue_conflicts"] == 1
    assert counts["queue_auth_required"] == 1
    assert counts["problem_total"] == 3

    item = summary_body["top_laggers"][0]
    assert item["installer_id"] == str(installer.id)
    assert item["status"] == "DANGER"
    assert item["failed_events"] == 1
    assert item["queue_conflicts"] == 1
    assert item["queue_auth_required"] == 1
    assert item["problem_count"] == 3


def test_sync_health_failed_webhook_does_not_consume_alert_cooldown(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    monkeypatch,
):
    installer = make_installer(
        full_name="Retryable Sync Alert Installer",
        phone="+972501110001",
    )
    db_session.add(
        InstallerSyncStateORM(
            company_id=company_id,
            installer_id=installer.id,
            last_cursor_ack=0,
            last_seen_at=None,
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        settings,
        "SYNC_ALERT_WEBHOOK_URL",
        "https://alerts.example.test/sync",
    )

    def fail_delivery(*_args, **_kwargs):
        raise httpx.ConnectError("delivery unavailable")

    monkeypatch.setattr(httpx, "post", fail_delivery)

    failed_response = client_admin_real_uow.post("/api/v1/admin/sync/health/run")
    assert failed_response.status_code == 200, failed_response.text
    assert failed_response.json()["data"]["alerts_sent"] == 0

    db_session.expire_all()
    state = db_session.execute(
        select(InstallerSyncStateORM).where(
            InstallerSyncStateORM.company_id == company_id,
            InstallerSyncStateORM.installer_id == installer.id,
        )
    ).scalar_one()
    assert state.last_alert_at is None
    assert state.last_alert_lag is None

    deliveries = []

    class SuccessfulResponse:
        @staticmethod
        def raise_for_status() -> None:
            return None

    def deliver(*args, **kwargs):
        deliveries.append((args, kwargs))
        return SuccessfulResponse()

    monkeypatch.setattr(httpx, "post", deliver)

    success_response = client_admin_real_uow.post("/api/v1/admin/sync/health/run")
    assert success_response.status_code == 200, success_response.text
    assert success_response.json()["data"]["alerts_sent"] == 1
    assert len(deliveries) == 1

    db_session.expire_all()
    state = db_session.execute(
        select(InstallerSyncStateORM).where(
            InstallerSyncStateORM.company_id == company_id,
            InstallerSyncStateORM.installer_id == installer.id,
        )
    ).scalar_one()
    assert state.last_alert_at is not None
    assert state.last_alert_lag == 0


def test_sync_admin_health_forbidden_for_installer(client_installer):
    run_resp = client_installer.post("/api/v1/admin/sync/health/run")
    assert run_resp.status_code == 403, run_resp.text
    assert run_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    summary_resp = client_installer.get("/api/v1/admin/sync/health/summary")
    assert summary_resp.status_code == 403, summary_resp.text
    assert summary_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"
