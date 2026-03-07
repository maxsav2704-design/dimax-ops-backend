from __future__ import annotations

import base64
import io
import json
import uuid

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _pdf_b64(lines: list[str]) -> str:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 800
    for line in lines:
        pdf.drawString(40, y, line)
        y -= 18
        if y < 40:
            pdf.showPage()
            y = 800
    pdf.save()
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _image_pdf_b64(lines: list[str]) -> str:
    image = Image.new("RGB", (2200, 1200), color="white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 58)
    except Exception:
        font = ImageFont.load_default()

    y = 80
    for line in lines:
        draw.text((80, y), line, fill="black", font=font)
        y += 120

    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    pdf_buffer = io.BytesIO()
    pdf = canvas.Canvas(pdf_buffer)
    pdf.drawImage(ImageReader(image_buffer), 20, 160, width=560, height=300)
    pdf.save()
    return base64.b64encode(pdf_buffer.getvalue()).decode("ascii")


def _create_project(client_admin_real_uow, *, name: str) -> str:
    resp = client_admin_real_uow.post(
        "/api/v1/admin/projects",
        json={"name": name, "address": f"{name} Address"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _create_door_type(client_admin_real_uow, *, code: str, name: str) -> str:
    resp = client_admin_real_uow.post(
        "/api/v1/admin/door-types",
        json={"code": code, "name": name, "is_active": True},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_project_import_file_csv_populates_structured_doors(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import CSV Project")
    _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    csv_payload = (
        "order_number,house,floor,apartment,location,marking,door_type,qty,price\n"
        "AZ-100,A,3,12,dira,D12,entrance,1,1000\n"
        "AZ-100,A,3,13,mamad,M13,entrance,2,900\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest.csv",
            "content_base64": _b64(csv_payload),
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["parsed_rows"] == 2
    assert body["prepared_rows"] == 3
    assert body["imported"] == 3
    assert body["skipped"] == 0
    assert body["errors"] == []

    details = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details.status_code == 200, details.text
    doors = details.json()["doors"]
    assert len(doors) == 3
    assert all(d["order_number"] == "AZ-100" for d in doors)
    assert any(d["apartment_number"] == "12" and d["location_code"] == "dira" for d in doors)
    assert any(d["apartment_number"] == "13" and d["door_marking"] == "M13" for d in doors)
    assert any(d["unit_label"].endswith("/1") or d["unit_label"].endswith("/2") for d in doors)


def test_project_import_file_json_with_default_door_type(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import JSON Project")
    door_type_id = _create_door_type(client_admin_real_uow, code="interior", name="Interior")

    data = [
        {
            "house_number": "B",
            "floor_label": "2",
            "apartment_number": "7",
            "location": "dira",
            "marking": "B2-7",
            "qty": 1,
        }
    ]
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "doors.json",
            "content_base64": base64.b64encode(json.dumps(data).encode("utf-8")).decode("ascii"),
            "default_door_type_id": door_type_id,
            "default_our_price": "555.50",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 1

    details = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details.status_code == 200, details.text
    door = details.json()["doors"][0]
    assert door["house_number"] == "B"
    assert door["floor_label"] == "2"
    assert door["apartment_number"] == "7"
    assert door["location_code"] == "dira"
    assert door["our_price"] == "555.50"


def test_project_import_file_xml_can_create_missing_door_types(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import XML Project")
    xml_payload = (
        "<rows>"
        "<row><house>A</house><floor>1</floor><apartment>1</apartment>"
        "<location>madregot</location><marking>S1</marking>"
        "<door_type>stair-door</door_type><qty>1</qty></row>"
        "</rows>"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "doors.xml",
            "content_base64": _b64(xml_payload),
            "create_missing_door_types": True,
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 1

    dtypes = client_admin_real_uow.get("/api/v1/admin/door-types?q=stair-door")
    assert dtypes.status_code == 200, dtypes.text
    assert any(x["code"] == "stair-door" for x in dtypes.json())


def test_project_import_file_forbidden_for_installer_and_validates_format(client_installer):
    project_id = uuid.uuid4()
    forbidden_resp = client_installer.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "x.csv",
            "content_base64": _b64("a,b\n1,2\n"),
        },
    )
    assert forbidden_resp.status_code == 403, forbidden_resp.text
    assert forbidden_resp.json()["error"]["code"] == "FORBIDDEN"

    forbidden_upload = client_installer.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-upload",
        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert forbidden_upload.status_code == 403, forbidden_upload.text
    assert forbidden_upload.json()["error"]["code"] == "FORBIDDEN"

    forbidden_profiles = client_installer.get("/api/v1/admin/projects/import-mapping-profiles")
    assert forbidden_profiles.status_code == 403, forbidden_profiles.text
    assert forbidden_profiles.json()["error"]["code"] == "FORBIDDEN"

    forbidden_history = client_installer.get(
        f"/api/v1/admin/projects/{project_id}/doors/import-history"
    )
    assert forbidden_history.status_code == 403, forbidden_history.text
    assert forbidden_history.json()["error"]["code"] == "FORBIDDEN"
    forbidden_details = client_installer.get(
        f"/api/v1/admin/projects/{project_id}/doors/import-runs/{uuid.uuid4()}"
    )
    assert forbidden_details.status_code == 403, forbidden_details.text
    assert forbidden_details.json()["error"]["code"] == "FORBIDDEN"

    forbidden_retry = client_installer.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-runs/{uuid.uuid4()}/retry",
    )
    assert forbidden_retry.status_code == 403, forbidden_retry.text
    assert forbidden_retry.json()["error"]["code"] == "FORBIDDEN"

    forbidden_bulk_reconcile = client_installer.post(
        "/api/v1/admin/projects/import-runs/reconcile-latest",
        json={"project_ids": [str(project_id)]},
    )
    assert forbidden_bulk_reconcile.status_code == 403, forbidden_bulk_reconcile.text
    assert forbidden_bulk_reconcile.json()["error"]["code"] == "FORBIDDEN"

    forbidden_failed_queue = client_installer.get(
        "/api/v1/admin/projects/import-runs/failed-queue"
    )
    assert forbidden_failed_queue.status_code == 403, forbidden_failed_queue.text
    assert forbidden_failed_queue.json()["error"]["code"] == "FORBIDDEN"

    forbidden_retry_failed = client_installer.post(
        "/api/v1/admin/projects/import-runs/retry-failed",
        json={"run_ids": [str(uuid.uuid4())]},
    )
    assert forbidden_retry_failed.status_code == 403, forbidden_retry_failed.text
    assert forbidden_retry_failed.json()["error"]["code"] == "FORBIDDEN"


def test_project_import_mapping_profiles_endpoint(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/projects/import-mapping-profiles")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["default_code"] == "auto_v1"
    codes = {x["code"] for x in body["items"]}
    assert {"auto_v1", "factory_he_v1", "factory_ru_v1", "generic_en_v1"} <= codes


def test_project_import_file_rejects_unsupported_extension(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import Bad Extension")
    resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "doors.docx",
            "content_base64": _b64("x"),
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_project_import_file_rejects_unknown_mapping_profile(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import Bad Mapping Profile")
    resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "doors.csv",
            "content_base64": _b64("house,floor,apartment,marking\nA,1,1,D1\n"),
            "mapping_profile": "unknown_profile",
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_project_import_file_upload_multipart(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import Multipart")
    _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    csv_payload = (
        "house,floor,apartment,location,marking,door_type,qty\n"
        "A,5,51,dira,D-51,entrance,1\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-upload",
        files={
            "file": ("factory_manifest.csv", csv_payload.encode("utf-8"), "text/csv")
        },
        data={
            "default_our_price": "0",
            "create_missing_door_types": "false",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 1

    details = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details.status_code == 200, details.text
    door = details.json()["doors"][0]
    assert door["apartment_number"] == "51"
    assert door["location_code"] == "dira"
    assert door["door_marking"] == "D-51"


def test_project_import_file_upload_multipart_supports_exact_hebrew_factory_columns(
    client_admin_real_uow,
):
    project_id = _create_project(client_admin_real_uow, name="Import Multipart Hebrew")
    _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    col_house = "\u05d1\u05e0\u05d9\u05d9\u05df"
    col_floor = "\u05e7\u05d5\u05de\u05d4"
    col_apartment = "\u05d3\u05d9\u05e8\u05d4"
    col_wing_model = "\u05d3\u05d2\u05dd \u05db\u05e0\u05e3"
    col_order_number = "\u05de\u05e1\u05e4\u05e8 \u05d4\u05d6\u05de\u05e0\u05d4"

    csv_payload = (
        f"{col_order_number},{col_house},{col_floor},{col_apartment},{col_wing_model},door_type,qty\n"
        "AZ-905,A,9,905,D-905,entrance,1\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-upload",
        files={
            "file": (
                "factory_manifest_hebrew_upload.csv",
                csv_payload.encode("utf-8-sig"),
                "text/csv",
            )
        },
        data={
            "default_our_price": "0",
            "create_missing_door_types": "false",
            "mapping_profile": "factory_he_v1",
            "delimiter": ",",
            "analyze_only": "true",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["mode"] == "analyze"
    assert body["would_import"] == 1
    required = {x["field_key"]: x for x in body["diagnostics"]["required_fields"]}
    assert required["house_number"]["found"] is True
    assert required["floor_label"]["found"] is True
    assert required["apartment_number"]["found"] is True
    assert required["door_marking"]["found"] is True
    assert required["order_number"]["found"] is True
    assert body["diagnostics"]["mapping_profile"] == "factory_he_v1"
    assert body["diagnostics"]["data_summary"]["unique_order_numbers"] == 1
    assert body["diagnostics"]["preview_groups"][0]["order_number"] == "AZ-905"
    assert body["diagnostics"]["preview_groups"][0]["door_marking"] == "D-905"


def test_project_import_file_analyze_only_preflight_does_not_write(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import Analyze Only")
    door_type_id = _create_door_type(client_admin_real_uow, code="preflight", name="Preflight")

    csv_payload = "house,floor,apartment,marking,qty\nA,8,801,P-801,1\n"
    analyze_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_preflight.csv",
            "content_base64": _b64(csv_payload),
            "default_door_type_id": door_type_id,
            "default_our_price": "0",
            "analyze_only": True,
        },
    )
    assert analyze_resp.status_code == 200, analyze_resp.text
    analyze_body = analyze_resp.json()
    assert analyze_body["mode"] == "analyze"
    assert analyze_body["imported"] == 0
    assert analyze_body["would_import"] == 1
    assert analyze_body["would_skip"] == 0

    details_before = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details_before.status_code == 200, details_before.text
    assert details_before.json()["doors"] == []

    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_preflight.csv",
            "content_base64": _b64(csv_payload),
            "default_door_type_id": door_type_id,
            "default_our_price": "0",
            "analyze_only": False,
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["mode"] == "import"
    assert import_resp.json()["imported"] == 1

    details_after = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details_after.status_code == 200, details_after.text
    assert len(details_after.json()["doors"]) == 1


def test_project_import_file_idempotency_prevents_duplicate_apply(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import Idempotency")
    door_type_id = _create_door_type(
        client_admin_real_uow,
        code="idempotent",
        name="Idempotent",
    )

    csv_payload = "house,floor,apartment,marking,qty\nA,2,201,ID-201,1\n"
    body = {
        "filename": "factory_manifest_idempotent.csv",
        "content_base64": _b64(csv_payload),
        "default_door_type_id": door_type_id,
        "default_our_price": "0",
        "analyze_only": False,
    }

    first = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json=body,
    )
    assert first.status_code == 200, first.text
    assert first.json()["imported"] == 1
    assert first.json()["idempotency_hit"] is False

    second = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json=body,
    )
    assert second.status_code == 200, second.text
    assert second.json()["idempotency_hit"] is True
    assert second.json()["imported"] == 1

    details = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details.status_code == 200, details.text
    assert len(details.json()["doors"]) == 1


def test_project_import_file_history_and_retry(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import History Retry")
    door_type_id = _create_door_type(
        client_admin_real_uow,
        code="history-retry",
        name="History Retry",
    )

    csv_payload = "house,floor,apartment,marking,qty\nA,6,601,H-601,1\n"
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_history.csv",
            "content_base64": _b64(csv_payload),
            "default_door_type_id": door_type_id,
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 1

    history_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}/doors/import-history?limit=20&offset=0"
    )
    assert history_resp.status_code == 200, history_resp.text
    history_items = history_resp.json()["items"]
    assert history_items
    latest = history_items[0]
    assert latest["mode"] == "import"
    assert latest["retry_available"] is True
    assert latest["status"] == "SUCCESS"
    details_resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}/doors/import-runs/{latest['id']}"
    )
    assert details_resp.status_code == 200, details_resp.text
    details_body = details_resp.json()
    assert details_body["id"] == latest["id"]
    assert details_body["mode"] == "import"
    assert details_body["diagnostics"]["data_summary"]["unique_houses"] == 1
    assert details_body["diagnostics"]["preview_groups"][0]["house_number"] == "A"
    assert details_body["diagnostics"]["preview_groups"][0]["door_count"] == 1
    assert details_body["errors"] == []

    retry_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-runs/{latest['id']}/retry"
    )
    assert retry_resp.status_code == 200, retry_resp.text
    retry_body = retry_resp.json()
    assert retry_body["mode"] == "import_retry"
    assert retry_body["imported"] == 0
    assert retry_body["skipped"] >= 1

    history_after = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}/doors/import-history?limit=20&offset=0"
    )
    assert history_after.status_code == 200, history_after.text
    modes = [x["mode"] for x in history_after.json()["items"]]
    assert "import_retry" in modes

    report_retry = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs"
        "?entity_type=project&action=PROJECT_DOORS_IMPORT_RETRY"
    )
    assert report_retry.status_code == 200, report_retry.text
    retry_items = report_retry.json()["items"]
    assert any(x["entity_id"] == project_id for x in retry_items)


def test_project_import_history_rejects_unknown_mode(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import Bad Mode Filter")
    resp = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_id}/doors/import-history?mode=unknown_mode"
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_project_bulk_reconcile_latest_imports(client_admin_real_uow):
    project_a = _create_project(client_admin_real_uow, name="Bulk Reconcile A")
    project_b = _create_project(client_admin_real_uow, name="Bulk Reconcile B")
    project_empty = _create_project(client_admin_real_uow, name="Bulk Reconcile Empty")
    missing_project = str(uuid.uuid4())
    door_type_id = _create_door_type(
        client_admin_real_uow,
        code="bulk-reconcile",
        name="Bulk Reconcile",
    )

    payload_a = "house,floor,apartment,marking,qty\nA,3,301,BR-301,1\n"
    payload_b = "house,floor,apartment,marking,qty\nB,4,401,BR-401,1\n"

    resp_a = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_a}/doors/import-file",
        json={
            "filename": "bulk_reconcile_a.csv",
            "content_base64": _b64(payload_a),
            "default_door_type_id": door_type_id,
            "default_our_price": "0",
        },
    )
    assert resp_a.status_code == 200, resp_a.text
    assert resp_a.json()["imported"] == 1

    resp_b = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_b}/doors/import-file",
        json={
            "filename": "bulk_reconcile_b.csv",
            "content_base64": _b64(payload_b),
            "default_door_type_id": door_type_id,
            "default_our_price": "0",
        },
    )
    assert resp_b.status_code == 200, resp_b.text
    assert resp_b.json()["imported"] == 1

    reconcile_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/import-runs/reconcile-latest",
        json={
            "project_ids": [project_a, project_b, project_empty, missing_project],
        },
    )
    assert reconcile_resp.status_code == 200, reconcile_resp.text
    body = reconcile_resp.json()
    assert body["total_projects"] == 4
    assert body["successful_projects"] == 2
    assert body["failed_projects"] == 1
    assert body["skipped_projects"] == 1
    items = {item["project_id"]: item for item in body["items"]}

    assert items[project_a]["status"] == "SUCCESS"
    assert items[project_a]["source_run_id"] is not None
    assert items[project_a]["skipped"] >= 1

    assert items[project_b]["status"] == "SUCCESS"
    assert items[project_b]["source_run_id"] is not None
    assert items[project_b]["skipped"] >= 1

    assert items[project_empty]["status"] == "SKIPPED_NO_RUN"
    assert items[project_empty]["source_run_id"] is None

    assert items[missing_project]["status"] == "FAILED_PROJECT_NOT_FOUND"
    assert items[missing_project]["errors_count"] == 1

    report_retry_bulk = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs"
        "?entity_type=project&action=PROJECT_DOORS_IMPORT_RETRY_BULK"
    )
    assert report_retry_bulk.status_code == 200, report_retry_bulk.text
    bulk_items = report_retry_bulk.json()["items"]
    assert any(x["entity_id"] == project_a for x in bulk_items)
    assert any(x["entity_id"] == project_b for x in bulk_items)


def test_project_bulk_reconcile_only_failed_runs(client_admin_real_uow):
    project_success = _create_project(client_admin_real_uow, name="Bulk Only Failed Success")
    project_partial = _create_project(client_admin_real_uow, name="Bulk Only Failed Partial")
    door_type_id = _create_door_type(
        client_admin_real_uow,
        code="bulk-only-failed",
        name="Bulk Only Failed",
    )

    success_payload = "house,floor,apartment,marking,qty\nA,1,101,OK-101,1\n"
    success_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_success}/doors/import-file",
        json={
            "filename": "bulk_only_failed_success.csv",
            "content_base64": _b64(success_payload),
            "default_door_type_id": door_type_id,
            "default_our_price": "0",
        },
    )
    assert success_resp.status_code == 200, success_resp.text
    assert success_resp.json()["imported"] == 1

    partial_payload = (
        "house,floor,apartment,marking,door_type,price,qty\n"
        "A,2,201,PR-201,bulk-only-failed,100,1\n"
        "A,2,202,PR-202,bulk-only-failed,invalid,1\n"
    )
    partial_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_partial}/doors/import-file",
        json={
            "filename": "bulk_only_failed_partial.csv",
            "content_base64": _b64(partial_payload),
            "default_our_price": "0",
        },
    )
    assert partial_resp.status_code == 200, partial_resp.text
    assert partial_resp.json()["imported"] == 1
    assert len(partial_resp.json()["errors"]) >= 1

    reconcile_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/import-runs/reconcile-latest",
        json={
            "project_ids": [project_success, project_partial],
            "only_failed_runs": True,
        },
    )
    assert reconcile_resp.status_code == 200, reconcile_resp.text
    body = reconcile_resp.json()
    assert body["total_projects"] == 2
    assert body["successful_projects"] == 1
    assert body["failed_projects"] == 0
    assert body["skipped_projects"] == 1
    items = {item["project_id"]: item for item in body["items"]}

    assert items[project_success]["status"] == "SKIPPED_NOT_FAILED"
    assert items[project_success]["source_run_id"] is not None
    assert items[project_partial]["status"] == "SUCCESS"
    assert items[project_partial]["source_run_id"] is not None
    assert items[project_partial]["skipped"] >= 1


def test_project_failed_queue_and_retry_failed_runs_bulk(client_admin_real_uow):
    project_success = _create_project(client_admin_real_uow, name="Queue Success")
    project_partial = _create_project(client_admin_real_uow, name="Queue Partial")
    door_type_id = _create_door_type(
        client_admin_real_uow,
        code="queue-retry",
        name="Queue Retry",
    )

    ok_payload = "house,floor,apartment,marking,qty\nA,1,11,Q-11,1\n"
    ok_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_success}/doors/import-file",
        json={
            "filename": "queue_success.csv",
            "content_base64": _b64(ok_payload),
            "default_door_type_id": door_type_id,
            "default_our_price": "0",
        },
    )
    assert ok_resp.status_code == 200, ok_resp.text
    assert ok_resp.json()["imported"] == 1

    partial_payload = (
        "house,floor,apartment,marking,door_type,price,qty\n"
        "A,2,21,Q-21,queue-retry,100,1\n"
        "A,2,22,Q-22,queue-retry,bad_price,1\n"
    )
    partial_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_partial}/doors/import-file",
        json={
            "filename": "queue_partial.csv",
            "content_base64": _b64(partial_payload),
            "default_our_price": "0",
        },
    )
    assert partial_resp.status_code == 200, partial_resp.text
    assert partial_resp.json()["imported"] == 1
    assert len(partial_resp.json()["errors"]) >= 1

    queue_resp = client_admin_real_uow.get(
        "/api/v1/admin/projects/import-runs/failed-queue?limit=20&offset=0"
    )
    assert queue_resp.status_code == 200, queue_resp.text
    queue = queue_resp.json()
    assert queue["total"] >= 1
    queue_items = queue["items"]
    assert any(item["project_id"] == project_partial for item in queue_items)
    assert all(item["status"] in {"FAILED", "PARTIAL"} for item in queue_items)
    partial_run = next(item for item in queue_items if item["project_id"] == project_partial)
    assert partial_run["retry_available"] is True

    history_success = client_admin_real_uow.get(
        f"/api/v1/admin/projects/{project_success}/doors/import-history?limit=10&offset=0"
    )
    assert history_success.status_code == 200, history_success.text
    success_run_id = history_success.json()["items"][0]["id"]

    retry_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects/import-runs/retry-failed",
        json={
            "run_ids": [success_run_id, partial_run["run_id"]],
        },
    )
    assert retry_resp.status_code == 200, retry_resp.text
    retry_body = retry_resp.json()
    assert retry_body["total_runs"] == 2
    assert retry_body["successful_runs"] == 1
    assert retry_body["skipped_runs"] == 1
    by_run = {item["run_id"]: item for item in retry_body["items"]}
    assert by_run[success_run_id]["status"] == "SKIPPED_NOT_FAILED"
    assert by_run[partial_run["run_id"]]["status"] == "SUCCESS"


def test_project_import_file_writes_audit_for_analyze_and_apply(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import Audit Trail")
    door_type_id = _create_door_type(
        client_admin_real_uow,
        code="audit-import",
        name="Audit Import",
    )

    csv_payload = "house,floor,apartment,marking,qty\nA,9,901,IMP-901,1\n"
    analyze_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_audit.csv",
            "content_base64": _b64(csv_payload),
            "default_door_type_id": door_type_id,
            "default_our_price": "0",
            "analyze_only": True,
        },
    )
    assert analyze_resp.status_code == 200, analyze_resp.text

    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_audit.csv",
            "content_base64": _b64(csv_payload),
            "default_door_type_id": door_type_id,
            "default_our_price": "0",
            "analyze_only": False,
        },
    )
    assert import_resp.status_code == 200, import_resp.text

    report_analyze = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs"
        "?entity_type=project&action=PROJECT_DOORS_IMPORT_ANALYZE"
    )
    assert report_analyze.status_code == 200, report_analyze.text
    analyze_items = report_analyze.json()["items"]
    assert analyze_items
    analyze_row = next(
        x for x in analyze_items if x["entity_id"] == project_id
    )
    assert analyze_row["action"] == "PROJECT_DOORS_IMPORT_ANALYZE"
    assert analyze_row["after"]["filename"] == "factory_manifest_audit.csv"
    assert analyze_row["after"]["mode"] == "analyze"
    assert analyze_row["after"]["would_import"] >= 1

    report_apply = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-catalogs"
        "?entity_type=project&action=PROJECT_DOORS_IMPORT_APPLY"
    )
    assert report_apply.status_code == 200, report_apply.text
    apply_items = report_apply.json()["items"]
    assert apply_items
    apply_row = next(x for x in apply_items if x["entity_id"] == project_id)
    assert apply_row["action"] == "PROJECT_DOORS_IMPORT_APPLY"
    assert apply_row["after"]["mode"] == "import"
    assert apply_row["after"]["imported"] >= 1
    assert apply_row["after"]["errors_count"] == 0


def test_project_import_file_normalizes_multilang_headers_and_locations(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import MultiLang")
    _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    csv_payload = (
        "номер дома,этаж,квартира,локация,маркировка,door_type,количество\n"
        "A,4,41,дира,D-41,entrance,1\n"
        "A,4,42,חדר אשפה,H-42,entrance,1\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_ru_he.csv",
            "content_base64": _b64(csv_payload),
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 2

    details = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details.status_code == 200, details.text
    doors = details.json()["doors"]
    assert len(doors) == 2
    assert any(d["apartment_number"] == "41" and d["location_code"] == "dira" for d in doors)
    assert any(
        d["apartment_number"] == "42" and d["location_code"] == "heder_ashpa"
        for d in doors
    )


def test_project_import_file_does_not_use_regular_marking_as_location(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import Marking Safeguard")
    _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    csv_payload = (
        "house,floor,apartment,location,marking,door_type,qty\n"
        "A,1,1,,D12,entrance,1\n"
        "A,1,2,,ממד,entrance,1\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_marking.csv",
            "content_base64": _b64(csv_payload),
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 2

    details = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details.status_code == 200, details.text
    doors = sorted(details.json()["doors"], key=lambda d: d["apartment_number"] or "")
    assert doors[0]["apartment_number"] == "1"
    assert doors[0]["door_marking"] == "D12"
    assert doors[0]["location_code"] is None
    assert doors[1]["apartment_number"] == "2"
    assert doors[1]["door_marking"] == "ממד"
    assert doors[1]["location_code"] == "mamad"


def test_project_import_file_supports_exact_hebrew_factory_columns(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import Hebrew Factory Columns")
    _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    col_house = "\u05d1\u05e0\u05d9\u05d9\u05df"
    col_floor = "\u05e7\u05d5\u05de\u05d4"
    col_apartment = "\u05d3\u05d9\u05e8\u05d4"
    col_wing_model = "\u05d3\u05d2\u05dd \u05db\u05e0\u05e3"
    col_order_number = "\u05de\u05e1\u05e4\u05e8 \u05d4\u05d6\u05de\u05e0\u05d4"

    csv_payload = (
        f"{col_order_number},{col_house},{col_floor},{col_apartment},{col_wing_model},door_type,qty\n"
        "AZ-904,A,9,904,D-904,entrance,1\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_hebrew_cols.csv",
            "content_base64": _b64(csv_payload),
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["imported"] == 1
    required = {x["field_key"]: x for x in body["diagnostics"]["required_fields"]}
    assert required["house_number"]["found"] is True
    assert required["floor_label"]["found"] is True
    assert required["apartment_number"]["found"] is True
    assert required["door_marking"]["found"] is True
    assert required["order_number"]["found"] is True
    assert body["diagnostics"]["data_summary"]["unique_order_numbers"] == 1
    assert body["diagnostics"]["data_summary"]["unique_houses"] == 1
    assert body["diagnostics"]["data_summary"]["unique_floors"] == 1
    assert body["diagnostics"]["data_summary"]["unique_apartments"] == 1
    assert body["diagnostics"]["data_summary"]["unique_markings"] == 1
    assert body["diagnostics"]["preview_groups"][0]["order_number"] == "AZ-904"
    assert body["diagnostics"]["preview_groups"][0]["door_marking"] == "D-904"

    details = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details.status_code == 200, details.text
    door = details.json()["doors"][0]
    assert door["order_number"] == "AZ-904"
    assert door["house_number"] == "A"
    assert door["floor_label"] == "9"
    assert door["apartment_number"] == "904"
    assert door["door_marking"] == "D-904"


def test_project_import_file_factory_profile_uses_wing_model_as_door_type_code(
    client_admin_real_uow,
):
    project_id = _create_project(client_admin_real_uow, name="Import Hebrew Wing Fallback")

    col_house = "\u05d1\u05e0\u05d9\u05d9\u05df"
    col_floor = "\u05e7\u05d5\u05de\u05d4"
    col_apartment = "\u05d3\u05d9\u05e8\u05d4"
    col_wing_model = "\u05d3\u05d2\u05dd \u05db\u05e0\u05e3"
    col_order_number = "\u05de\u05e1\u05e4\u05e8 \u05d4\u05d6\u05de\u05e0\u05d4"

    csv_payload = (
        f"{col_order_number},{col_house},{col_floor},{col_apartment},{col_wing_model},qty\n"
        "AZ-905,A,9,905,D-905,1\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_hebrew_wing_fallback.csv",
            "content_base64": _b64(csv_payload),
            "mapping_profile": "factory_he_v1",
            "delimiter": ",",
            "create_missing_door_types": True,
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["imported"] == 1
    assert body["diagnostics"]["preview_groups"][0]["door_marking"] == "D-905"

    details = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details.status_code == 200, details.text
    door = details.json()["doors"][0]
    assert door["order_number"] == "AZ-905"
    assert door["door_marking"] == "D-905"
    assert door["apartment_number"] == "905"

    dtypes = client_admin_real_uow.get("/api/v1/admin/door-types?q=d-905")
    assert dtypes.status_code == 200, dtypes.text
    assert any(x["code"] == "d-905" for x in dtypes.json())


def test_project_import_factory_profile_requires_hebrew_required_columns_by_default(
    client_admin_real_uow,
):
    project_id = _create_project(client_admin_real_uow, name="Import Hebrew Strict Columns")
    _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    col_house = "\u05d1\u05e0\u05d9\u05d9\u05df"
    col_floor = "\u05e7\u05d5\u05de\u05d4"
    col_apartment = "\u05d3\u05d9\u05e8\u05d4"

    csv_payload = (
        f"{col_house},{col_floor},{col_apartment},door_type,qty\n"
        "A,9,905,entrance,1\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_hebrew_missing_marking.csv",
            "content_base64": _b64(csv_payload),
            "mapping_profile": "factory_he_v1",
            "delimiter": ",",
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 422, import_resp.text
    assert import_resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "missing required columns" in import_resp.json()["error"]["message"]


def test_project_import_strict_required_fields_can_be_disabled(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import Hebrew Strict Off")
    _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    col_house = "\u05d1\u05e0\u05d9\u05d9\u05df"
    col_floor = "\u05e7\u05d5\u05de\u05d4"
    col_apartment = "\u05d3\u05d9\u05e8\u05d4"

    csv_payload = (
        f"{col_house},{col_floor},{col_apartment},door_type,qty\n"
        "A,9,906,entrance,1\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_hebrew_missing_marking_allowed.csv",
            "content_base64": _b64(csv_payload),
            "mapping_profile": "factory_he_v1",
            "delimiter": ",",
            "strict_required_fields": False,
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["imported"] == 1
    assert import_resp.json()["diagnostics"]["strict_required_fields"] is False
    assert "door_marking" in import_resp.json()["diagnostics"]["missing_required_fields"]
    assert "order_number" in import_resp.json()["diagnostics"]["missing_required_fields"]


def test_project_import_file_upload_factory_profile_uses_wing_model_as_door_type_code(
    client_admin_real_uow,
):
    project_id = _create_project(client_admin_real_uow, name="Import Multipart Hebrew Wing Fallback")

    col_house = "\u05d1\u05e0\u05d9\u05d9\u05df"
    col_floor = "\u05e7\u05d5\u05de\u05d4"
    col_apartment = "\u05d3\u05d9\u05e8\u05d4"
    col_wing_model = "\u05d3\u05d2\u05dd \u05db\u05e0\u05e3"
    col_order_number = "\u05de\u05e1\u05e4\u05e8 \u05d4\u05d6\u05de\u05e0\u05d4"

    csv_payload = (
        f"{col_order_number},{col_house},{col_floor},{col_apartment},{col_wing_model},qty\n"
        "AZ-906,A,9,906,D-906,1\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-upload",
        files={
            "file": (
                "factory_manifest_hebrew_wing_upload.csv",
                csv_payload.encode("utf-8-sig"),
                "text/csv",
            )
        },
        data={
            "default_our_price": "0",
            "create_missing_door_types": "true",
            "mapping_profile": "factory_he_v1",
            "delimiter": ",",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["imported"] == 1

    details = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details.status_code == 200, details.text
    door = details.json()["doors"][0]
    assert door["order_number"] == "AZ-906"
    assert door["door_marking"] == "D-906"
    assert door["apartment_number"] == "906"


def test_project_import_strict_required_fields_rejects_rows_missing_required_values(
    client_admin_real_uow,
):
    project_id = _create_project(client_admin_real_uow, name="Import Strict Missing Values")
    _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    csv_payload = (
        "order_number,house,floor,apartment,marking,door_type,qty\n"
        "AZ-907,A,9,,D-907,entrance,1\n"
    )
    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_strict_missing_values.csv",
            "content_base64": _b64(csv_payload),
            "mapping_profile": "auto_v1",
            "strict_required_fields": True,
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 422, import_resp.text
    assert import_resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "missing required row values" in import_resp.json()["error"]["message"]


def test_project_import_file_pdf_tabular_rows(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import PDF Project")
    _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    pdf_content_b64 = _pdf_b64(
        [
            "house,floor,apartment,marking,door_type,qty",
            "A,10,1001,D-1001,entrance,1",
            "A,10,1002,D-1002,entrance,2",
        ]
    )

    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest.pdf",
            "content_base64": pdf_content_b64,
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["parsed_rows"] >= 2
    assert body["imported"] == 3

    details = client_admin_real_uow.get(f"/api/v1/admin/projects/{project_id}")
    assert details.status_code == 200, details.text
    doors = details.json()["doors"]
    assert len(doors) == 3
    assert any(d["apartment_number"] == "1001" and d["door_marking"] == "D-1001" for d in doors)
    assert any(d["apartment_number"] == "1002" and d["unit_label"].endswith("/1") for d in doors)
    assert any(d["apartment_number"] == "1002" and d["unit_label"].endswith("/2") for d in doors)


def test_project_import_file_pdf_ocr_image_only(client_admin_real_uow):
    project_id = _create_project(client_admin_real_uow, name="Import OCR PDF Project")
    door_type_id = _create_door_type(client_admin_real_uow, code="entrance", name="Entrance")

    pdf_content_b64 = _image_pdf_b64(
        [
            "house,floor,apartment,marking,qty",
            "A,11,1101,D-1101,1",
            "A,11,1102,D-1102,1",
        ]
    )

    import_resp = client_admin_real_uow.post(
        f"/api/v1/admin/projects/{project_id}/doors/import-file",
        json={
            "filename": "factory_manifest_scan.pdf",
            "content_base64": pdf_content_b64,
            "default_door_type_id": door_type_id,
            "default_our_price": "0",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["parsed_rows"] >= 1
    assert body["imported"] >= 1
