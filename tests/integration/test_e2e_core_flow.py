from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from app.modules.identity.domain.enums import UserRole


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(client_raw, *, company_id: str, email: str, password: str) -> dict:
    resp = client_raw.post(
        "/api/v1/auth/login",
        json={
            "company_id": company_id,
            "email": email,
            "password": password,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_e2e_auth_projects_addons_journal_sync_flow(
    client_raw,
    company_id,
    make_user,
    make_door_type,
):
    admin_password = "AdminStrong123"
    installer_password = "InstallerStrong123"
    admin_user = make_user(role=UserRole.ADMIN, password=admin_password)
    installer_user = make_user(
        role=UserRole.INSTALLER, password=installer_password
    )

    admin_tokens = _login(
        client_raw,
        company_id=str(company_id),
        email=admin_user.email,
        password=admin_password,
    )
    admin_headers = _auth_header(admin_tokens["access_token"])

    create_installer_resp = client_raw.post(
        "/api/v1/admin/installers",
        headers=admin_headers,
        json={
            "full_name": "E2E Installer",
            "phone": "+10000005001",
            "status": "ACTIVE",
            "is_active": True,
            "user_id": str(installer_user.id),
        },
    )
    assert create_installer_resp.status_code == 201, create_installer_resp.text
    installer_id = create_installer_resp.json()["id"]

    installer_tokens = _login(
        client_raw,
        company_id=str(company_id),
        email=installer_user.email,
        password=installer_password,
    )
    installer_headers = _auth_header(installer_tokens["access_token"])

    create_project_resp = client_raw.post(
        "/api/v1/admin/projects",
        headers=admin_headers,
        json={"name": "E2E Project", "address": "E2E Address"},
    )
    assert create_project_resp.status_code == 200, create_project_resp.text
    project_id = create_project_resp.json()["id"]

    door_type = make_door_type(name="E2E Door Type")
    import_resp = client_raw.post(
        f"/api/v1/admin/projects/{project_id}/doors/import",
        headers=admin_headers,
        json={
            "rows": [
                {
                    "door_type_id": str(door_type.id),
                    "unit_label": "A-01",
                    "our_price": "150.00",
                }
            ]
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 1

    details_resp = client_raw.get(
        f"/api/v1/admin/projects/{project_id}",
        headers=admin_headers,
    )
    assert details_resp.status_code == 200, details_resp.text
    door_id = details_resp.json()["doors"][0]["id"]

    assign_resp = client_raw.post(
        f"/api/v1/admin/projects/doors/{door_id}/assign-installer",
        headers=admin_headers,
        json={"installer_id": installer_id},
    )
    assert assign_resp.status_code == 200, assign_resp.text
    assert assign_resp.json()["ok"] is True

    installer_projects_resp = client_raw.get(
        "/api/v1/installer/projects",
        headers=installer_headers,
    )
    assert installer_projects_resp.status_code == 200, installer_projects_resp.text
    installer_project_ids = {x["id"] for x in installer_projects_resp.json()["items"]}
    assert project_id in installer_project_ids

    create_addon_type_resp = client_raw.post(
        "/api/v1/admin/addons/types",
        headers=admin_headers,
        json={
            "name": "E2E Addon",
            "unit": "pcs",
            "default_client_price": "20.00",
            "default_installer_price": "10.00",
        },
    )
    assert create_addon_type_resp.status_code == 200, create_addon_type_resp.text
    addon_type_id = create_addon_type_resp.json()["id"]

    set_plan_resp = client_raw.put(
        f"/api/v1/admin/addons/projects/{project_id}/plan",
        headers=admin_headers,
        json={
            "addon_type_id": addon_type_id,
            "qty_planned": "2.00",
            "client_price": "25.00",
            "installer_price": "12.00",
        },
    )
    assert set_plan_resp.status_code == 200, set_plan_resp.text
    assert len(set_plan_resp.json()["items"]) == 1

    add_fact_resp = client_raw.post(
        f"/api/v1/installer/addons/projects/{project_id}/facts",
        headers=installer_headers,
        json={
            "addon_type_id": addon_type_id,
            "qty_done": "1.00",
            "comment": "E2E fact",
            "client_event_id": "e2e-event-0001",
        },
    )
    assert add_fact_resp.status_code == 200, add_fact_resp.text
    assert add_fact_resp.json()["applied"] is True

    create_journal_resp = client_raw.post(
        "/api/v1/admin/journals",
        headers=admin_headers,
        json={"project_id": project_id, "title": "E2E Journal"},
    )
    assert create_journal_resp.status_code == 200, create_journal_resp.text
    journal_id = create_journal_resp.json()["id"]

    mark_ready_resp = client_raw.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready",
        headers=admin_headers,
    )
    assert mark_ready_resp.status_code == 200, mark_ready_resp.text
    public_token = mark_ready_resp.json()["public_token"]

    share_resp = client_raw.post(
        f"/api/v1/admin/journals/{journal_id}/pdf/share",
        headers=admin_headers,
        json={"ttl_sec": 300, "uses": 2, "audience": "+15550007777"},
    )
    assert share_resp.status_code == 200, share_resp.text
    share_url = share_resp.json()["url"]
    parsed = urlparse(share_url)
    file_download_resp = client_raw.get(f"{parsed.path}?{parsed.query}")
    assert file_download_resp.status_code == 200, file_download_resp.text
    assert file_download_resp.content.startswith(b"%PDF")

    send_resp = client_raw.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        headers=admin_headers,
        json={
            "send_email": False,
            "send_whatsapp": True,
            "whatsapp_to": "+15550007777",
            "message": "E2E send",
        },
    )
    assert send_resp.status_code == 200, send_resp.text
    assert send_resp.json()["enqueued"]["whatsapp"] is True

    public_get_resp = client_raw.get(f"/api/v1/public/journals/{public_token}")
    assert public_get_resp.status_code == 200, public_get_resp.text
    assert public_get_resp.json()["journal"]["status"] == "ACTIVE"

    sign_resp = client_raw.post(
        f"/api/v1/public/journals/{public_token}/sign",
        json={"signer_name": "E2E Client", "signature_payload": {"ok": True}},
    )
    assert sign_resp.status_code == 200, sign_resp.text
    assert sign_resp.json()["ok"] is True

    journal_details_resp = client_raw.get(
        f"/api/v1/admin/journals/{journal_id}",
        headers=admin_headers,
    )
    assert journal_details_resp.status_code == 200, journal_details_resp.text
    assert journal_details_resp.json()["status"] == "ARCHIVED"

    sync_resp = client_raw.post(
        "/api/v1/installer/sync",
        headers=installer_headers,
        json={
            "since_cursor": 0,
            "ack_cursor": 0,
            "events": [],
            "app_version": "e2e",
            "device_id": "e2e-device",
        },
    )
    assert sync_resp.status_code == 200, sync_resp.text
    sync_body = sync_resp.json()
    assert isinstance(sync_body["next_cursor"], int)
    assert isinstance(sync_body["changes"], list)
    assert isinstance(sync_body["acks"], list)

    installer_project_details_resp = client_raw.get(
        f"/api/v1/installer/projects/{project_id}",
        headers=installer_headers,
    )
    assert (
        installer_project_details_resp.status_code == 200
    ), installer_project_details_resp.text
    assert installer_project_details_resp.json()["id"] == project_id

    now = datetime.now(timezone.utc).replace(microsecond=0)
    calendar_create_resp = client_raw.post(
        "/api/v1/admin/calendar/events",
        headers=admin_headers,
        json={
            "title": "E2E Calendar",
            "event_type": "delivery",
            "starts_at": now.isoformat().replace("+00:00", "Z"),
            "ends_at": (now + timedelta(hours=1)).isoformat().replace(
                "+00:00", "Z"
            ),
            "installer_ids": [installer_id],
        },
    )
    assert calendar_create_resp.status_code == 200, calendar_create_resp.text
