from __future__ import annotations

import uuid


def test_door_types_export_import_and_bulk_flow(client_admin_real_uow):
    create_a = client_admin_real_uow.post(
        "/api/v1/admin/door-types",
        json={"code": "std-a", "name": "Standard A", "is_active": True},
    )
    assert create_a.status_code == 201, create_a.text
    door_a = create_a.json()

    create_b = client_admin_real_uow.post(
        "/api/v1/admin/door-types",
        json={"code": "std-b", "name": "Standard B", "is_active": True},
    )
    assert create_b.status_code == 201, create_b.text
    door_b = create_b.json()

    export_resp = client_admin_real_uow.get("/api/v1/admin/door-types/export")
    assert export_resp.status_code == 200, export_resp.text
    exported = export_resp.json()["items"]
    assert any(x["code"] == "std-a" for x in exported)
    assert any(x["code"] == "std-b" for x in exported)

    import_resp = client_admin_real_uow.post(
        "/api/v1/admin/door-types/import",
        json={
            "create_only": False,
            "items": [
                {"code": "std-a", "name": "Standard A v2", "is_active": True},
                {"code": "std-c", "name": "Standard C", "is_active": False},
            ],
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    import_body = import_resp.json()
    assert import_body["created"] == 1
    assert import_body["updated"] == 1
    assert import_body["unchanged"] == 0
    assert import_body["skipped_existing"] == 0

    list_resp = client_admin_real_uow.get("/api/v1/admin/door-types")
    assert list_resp.status_code == 200, list_resp.text
    rows = list_resp.json()
    row_a = next(x for x in rows if x["id"] == door_a["id"])
    row_c = next(x for x in rows if x["code"] == "std-c")
    assert row_a["name"] == "Standard A v2"
    assert row_c["is_active"] is False

    bulk_deactivate = client_admin_real_uow.post(
        "/api/v1/admin/door-types/bulk",
        json={
            "ids": [door_b["id"], str(uuid.uuid4())],
            "operation": "deactivate",
        },
    )
    assert bulk_deactivate.status_code == 200, bulk_deactivate.text
    assert bulk_deactivate.json()["affected"] == 1
    assert bulk_deactivate.json()["not_found"] == 1

    door_b_get = client_admin_real_uow.get(f"/api/v1/admin/door-types/{door_b['id']}")
    assert door_b_get.status_code == 200, door_b_get.text
    assert door_b_get.json()["is_active"] is False

    bulk_delete = client_admin_real_uow.post(
        "/api/v1/admin/door-types/bulk",
        json={"ids": [door_b["id"]], "operation": "delete"},
    )
    assert bulk_delete.status_code == 200, bulk_delete.text
    assert bulk_delete.json()["affected"] == 1

    deleted_get = client_admin_real_uow.get(f"/api/v1/admin/door-types/{door_b['id']}")
    assert deleted_get.status_code == 404, deleted_get.text


def test_reasons_import_create_only_and_bulk_activate(client_admin_real_uow):
    create_reason = client_admin_real_uow.post(
        "/api/v1/admin/reasons",
        json={"code": "missing-lock", "name": "Missing lock", "is_active": True},
    )
    assert create_reason.status_code == 201, create_reason.text
    reason = create_reason.json()

    import_resp = client_admin_real_uow.post(
        "/api/v1/admin/reasons/import",
        json={
            "create_only": True,
            "items": [
                {
                    "code": "missing-lock",
                    "name": "Missing lock renamed",
                    "is_active": False,
                },
                {"code": "broken-panel", "name": "Broken panel", "is_active": False},
            ],
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["created"] == 1
    assert body["updated"] == 0
    assert body["skipped_existing"] == 1

    original_get = client_admin_real_uow.get(f"/api/v1/admin/reasons/{reason['id']}")
    assert original_get.status_code == 200, original_get.text
    assert original_get.json()["name"] == "Missing lock"
    assert original_get.json()["is_active"] is True

    list_resp = client_admin_real_uow.get("/api/v1/admin/reasons")
    assert list_resp.status_code == 200, list_resp.text
    broken = next(x for x in list_resp.json() if x["code"] == "broken-panel")
    assert broken["is_active"] is False

    bulk_activate = client_admin_real_uow.post(
        "/api/v1/admin/reasons/bulk",
        json={"ids": [broken["id"]], "operation": "activate"},
    )
    assert bulk_activate.status_code == 200, bulk_activate.text
    assert bulk_activate.json()["affected"] == 1

    broken_get = client_admin_real_uow.get(f"/api/v1/admin/reasons/{broken['id']}")
    assert broken_get.status_code == 200, broken_get.text
    assert broken_get.json()["is_active"] is True


def test_reports_audit_catalogs_endpoint(client_admin_real_uow):
    door_create = client_admin_real_uow.post(
        "/api/v1/admin/door-types",
        json={"code": "audit-door", "name": "Audit Door", "is_active": True},
    )
    assert door_create.status_code == 201, door_create.text
    door_id = door_create.json()["id"]

    door_update = client_admin_real_uow.patch(
        f"/api/v1/admin/door-types/{door_id}",
        json={"name": "Audit Door v2"},
    )
    assert door_update.status_code == 200, door_update.text

    reason_create = client_admin_real_uow.post(
        "/api/v1/admin/reasons",
        json={"code": "audit-reason", "name": "Audit Reason", "is_active": True},
    )
    assert reason_create.status_code == 201, reason_create.text

    settings_update = client_admin_real_uow.patch(
        "/api/v1/admin/settings/company",
        json={"name": "DIMAX AUDIT COMPANY"},
    )
    assert settings_update.status_code == 200, settings_update.text

    report_resp = client_admin_real_uow.get("/api/v1/admin/reports/audit-catalogs")
    assert report_resp.status_code == 200, report_resp.text
    payload = report_resp.json()
    assert "items" in payload
    assert "summary" in payload
    assert payload["summary"]["total"] >= 3

    actions = {x["action"] for x in payload["items"]}
    assert "DOOR_TYPE_CREATE" in actions
    assert "DOOR_TYPE_UPDATE" in actions
    assert "REASON_CREATE" in actions
    assert "SETTINGS_COMPANY_UPDATE" in actions

    by_action = payload["summary"]["by_action"]
    assert by_action.get("DOOR_TYPE_CREATE", 0) >= 1

    filtered = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs?entity_type=door_type"
    )
    assert filtered.status_code == 200, filtered.text
    filtered_items = filtered.json()["items"]
    assert filtered_items
    assert all(x["entity_type"] == "door_type" for x in filtered_items)

    bad_filter = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs?entity_type=installer"
    )
    assert bad_filter.status_code == 422, bad_filter.text
    assert bad_filter.json()["error"]["code"] == "VALIDATION_ERROR"

    export_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs/export?entity_type=door_type"
    )
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.headers["content-type"].startswith("text/csv")
    assert "attachment;" in export_resp.headers["content-disposition"]
    csv_body = export_resp.text
    assert "id,created_at,actor_user_id,entity_type,entity_id,action,reason,before,after" in csv_body
    assert "DOOR_TYPE_CREATE" in csv_body or "DOOR_TYPE_UPDATE" in csv_body


def test_reports_audit_catalogs_include_installer_rate_actions(client_admin_real_uow):
    installer_create = client_admin_real_uow.post(
        "/api/v1/admin/installers",
        json={
            "full_name": "Rates Audit Installer",
            "phone": "+10000000024",
            "status": "ACTIVE",
            "is_active": True,
        },
    )
    assert installer_create.status_code == 201, installer_create.text
    installer_id = installer_create.json()["id"]

    door_type_create = client_admin_real_uow.post(
        "/api/v1/admin/door-types",
        json={"code": "audit-rate-door", "name": "Audit Rate Door", "is_active": True},
    )
    assert door_type_create.status_code == 201, door_type_create.text
    door_type_id = door_type_create.json()["id"]

    rate_create = client_admin_real_uow.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": installer_id,
            "door_type_id": door_type_id,
            "price": "180.00",
        },
    )
    assert rate_create.status_code == 201, rate_create.text
    rate_id = rate_create.json()["id"]

    rate_update = client_admin_real_uow.patch(
        f"/api/v1/admin/installer-rates/{rate_id}",
        json={"price": "200.00"},
    )
    assert rate_update.status_code == 200, rate_update.text

    rate_delete = client_admin_real_uow.delete(f"/api/v1/admin/installer-rates/{rate_id}")
    assert rate_delete.status_code == 204, rate_delete.text

    report_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs?entity_type=installer_rate"
    )
    assert report_resp.status_code == 200, report_resp.text
    payload = report_resp.json()
    assert payload["items"]
    assert all(x["entity_type"] == "installer_rate" for x in payload["items"])
    actions = {x["action"] for x in payload["items"]}
    assert "INSTALLER_RATE_CREATE" in actions
    assert "INSTALLER_RATE_UPDATE" in actions
    assert "INSTALLER_RATE_DELETE" in actions

    filtered = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs?action=INSTALLER_RATE_UPDATE"
    )
    assert filtered.status_code == 200, filtered.text
    filtered_items = filtered.json()["items"]
    assert filtered_items
    assert all(x["action"] == "INSTALLER_RATE_UPDATE" for x in filtered_items)

    export_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs/export?entity_type=installer_rate"
    )
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.headers["content-type"].startswith("text/csv")
    csv_body = export_resp.text
    assert "INSTALLER_RATE_CREATE" in csv_body
    assert "INSTALLER_RATE_UPDATE" in csv_body
    assert "INSTALLER_RATE_DELETE" in csv_body


def test_reports_audit_installer_rates_endpoint_and_export(client_admin_real_uow):
    installer_create = client_admin_real_uow.post(
        "/api/v1/admin/installers",
        json={
            "full_name": "Fin Audit Installer",
            "phone": "+10000000027",
            "status": "ACTIVE",
            "is_active": True,
        },
    )
    assert installer_create.status_code == 201, installer_create.text
    installer_id = installer_create.json()["id"]

    door_type_create = client_admin_real_uow.post(
        "/api/v1/admin/door-types",
        json={"code": "fin-audit-door", "name": "Fin Audit Door", "is_active": True},
    )
    assert door_type_create.status_code == 201, door_type_create.text
    door_type_id = door_type_create.json()["id"]

    create_rate = client_admin_real_uow.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": installer_id,
            "door_type_id": door_type_id,
            "price": "210.00",
        },
    )
    assert create_rate.status_code == 201, create_rate.text
    rate_id = create_rate.json()["id"]

    update_rate = client_admin_real_uow.patch(
        f"/api/v1/admin/installer-rates/{rate_id}",
        json={"price": "230.00"},
    )
    assert update_rate.status_code == 200, update_rate.text

    report_resp = client_admin_real_uow.get("/api/v1/admin/reports/audit-installer-rates")
    assert report_resp.status_code == 200, report_resp.text
    payload = report_resp.json()
    assert payload["summary"]["total"] >= 2
    assert payload["summary"]["by_entity"].get("installer_rate", 0) >= 2
    actions = {x["action"] for x in payload["items"]}
    assert "INSTALLER_RATE_CREATE" in actions
    assert "INSTALLER_RATE_UPDATE" in actions
    assert all(x["entity_type"] == "installer_rate" for x in payload["items"])

    filtered_by_action = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-installer-rates?action=INSTALLER_RATE_UPDATE"
    )
    assert filtered_by_action.status_code == 200, filtered_by_action.text
    assert filtered_by_action.json()["items"]
    assert all(
        x["action"] == "INSTALLER_RATE_UPDATE"
        for x in filtered_by_action.json()["items"]
    )

    filtered_by_rate = client_admin_real_uow.get(
        f"/api/v1/admin/reports/audit-installer-rates?rate_id={rate_id}"
    )
    assert filtered_by_rate.status_code == 200, filtered_by_rate.text
    assert filtered_by_rate.json()["items"]
    assert all(x["entity_id"] == rate_id for x in filtered_by_rate.json()["items"])

    bad_filter = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-installer-rates?action=DOOR_TYPE_CREATE"
    )
    assert bad_filter.status_code == 422, bad_filter.text
    assert bad_filter.json()["error"]["code"] == "VALIDATION_ERROR"

    export_resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/audit-installer-rates/export?rate_id={rate_id}"
    )
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.headers["content-type"].startswith("text/csv")
    assert "attachment;" in export_resp.headers["content-disposition"]
    csv_body = export_resp.text
    assert "id,created_at,actor_user_id,entity_type,entity_id,action,reason,before,after" in csv_body
    assert "INSTALLER_RATE_CREATE" in csv_body
    assert "INSTALLER_RATE_UPDATE" in csv_body


def test_catalog_bulk_and_audit_report_forbidden_for_installer(client_installer):
    for path, payload in (
        ("/api/v1/admin/door-types/export", None),
        ("/api/v1/admin/reasons/export", None),
        (
            "/api/v1/admin/door-types/import",
            {"create_only": False, "items": [{"code": "x1", "name": "X1"}]},
        ),
        (
            "/api/v1/admin/reasons/import",
            {"create_only": False, "items": [{"code": "x2", "name": "X2"}]},
        ),
        (
            "/api/v1/admin/door-types/bulk",
            {"ids": [str(uuid.uuid4())], "operation": "deactivate"},
        ),
        (
            "/api/v1/admin/reasons/bulk",
            {"ids": [str(uuid.uuid4())], "operation": "deactivate"},
        ),
        ("/api/v1/admin/reports/audit-catalogs", None),
        ("/api/v1/admin/reports/audit-catalogs/export", None),
        ("/api/v1/admin/reports/audit-installer-rates", None),
        ("/api/v1/admin/reports/audit-installer-rates/export", None),
    ):
        if payload is None:
            resp = client_installer.get(path)
        else:
            resp = client_installer.post(path, json=payload)
        assert resp.status_code == 403, f"{path}: {resp.text}"
        assert resp.json()["error"]["code"] == "FORBIDDEN"
