from __future__ import annotations


def _create_project(client, *, name: str = "Document Project") -> str:
    resp = client.post(
        "/api/v1/admin/projects",
        json={
            "code": "DOC-1",
            "name": name,
            "address": "HaYam 17, Ashdod",
            "contact_name": "Site Manager",
            "contact_phone": "+972501234567",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_admin_can_upload_fill_and_download_project_document(client):
    project_id = _create_project(client)

    template = (
        "Object: {{project.name}}\n"
        "Address: {{project.address}}\n"
        "Doors: {{doors.total}}\n"
        "Note: {{manual.note}}\n"
    ).encode("utf-8")

    upload_resp = client.post(
        "/api/v1/admin/documents/templates",
        data={"name": "Project Handover", "description": "Simple project document"},
        files={"file": ("handover.txt", template, "text/plain")},
    )
    assert upload_resp.status_code == 201, upload_resp.text
    uploaded = upload_resp.json()
    assert uploaded["source_filename"] == "handover.txt"
    assert uploaded["placeholders"] == [
        "doors.total",
        "manual.note",
        "project.address",
        "project.name",
    ]

    template_download_resp = client.get(
        f"/api/v1/admin/documents/templates/{uploaded['id']}/download"
    )
    assert template_download_resp.status_code == 200, template_download_resp.text
    assert "attachment" in template_download_resp.headers["content-disposition"]
    assert b"Object: {{project.name}}" in template_download_resp.content

    context_resp = client.get(f"/api/v1/admin/documents/projects/{project_id}/context")
    assert context_resp.status_code == 200, context_resp.text
    assert context_resp.json()["fields"]["project.name"] == "Document Project"
    assert context_resp.json()["fields"]["doors.total"] == 0

    render_resp = client.post(
        f"/api/v1/admin/documents/projects/{project_id}/render",
        json={
            "template_id": uploaded["id"],
            "overrides": {"manual.note": "Ready for client review"},
        },
    )
    assert render_resp.status_code == 200, render_resp.text
    generated = render_resp.json()
    assert generated["status"] == "READY"
    assert generated["template_name"] == "Project Handover"
    assert generated["project_name"] == "Document Project"
    assert generated["download_url"].startswith("/api/v1/admin/documents/generated/")

    list_resp = client.get(f"/api/v1/admin/documents/generated?project_id={project_id}")
    assert list_resp.status_code == 200, list_resp.text
    assert list_resp.json()["items"][0]["project_name"] == "Document Project"
    assert list_resp.json()["items"][0]["template_name"] == "Project Handover"

    download_resp = client.get(generated["download_url"])
    assert download_resp.status_code == 200, download_resp.text
    assert "attachment" in download_resp.headers["content-disposition"]
    assert b"Object: Document Project" in download_resp.content
    assert b"Note: Ready for client review" in download_resp.content


def test_admin_can_archive_and_restore_document_template(client):
    project_id = _create_project(client, name="Archive Project")
    upload_resp = client.post(
        "/api/v1/admin/documents/templates",
        data={"name": "Archive Candidate"},
        files={"file": ("archive.txt", b"Object: {{project.name}}", "text/plain")},
    )
    assert upload_resp.status_code == 201, upload_resp.text
    template_id = upload_resp.json()["id"]

    archive_resp = client.patch(
        f"/api/v1/admin/documents/templates/{template_id}",
        json={"is_active": False},
    )
    assert archive_resp.status_code == 200, archive_resp.text
    assert archive_resp.json()["is_active"] is False

    render_archived_resp = client.post(
        f"/api/v1/admin/documents/projects/{project_id}/render",
        json={"template_id": template_id, "overrides": {}},
    )
    assert render_archived_resp.status_code == 404, render_archived_resp.text

    restore_resp = client.patch(
        f"/api/v1/admin/documents/templates/{template_id}",
        json={"is_active": True},
    )
    assert restore_resp.status_code == 200, restore_resp.text
    assert restore_resp.json()["is_active"] is True

    render_restored_resp = client.post(
        f"/api/v1/admin/documents/projects/{project_id}/render",
        json={"template_id": template_id, "overrides": {}},
    )
    assert render_restored_resp.status_code == 200, render_restored_resp.text


def test_document_render_requires_all_template_placeholders(client):
    project_id = _create_project(client, name="Missing Field Project")
    upload_resp = client.post(
        "/api/v1/admin/documents/templates",
        data={"name": "Missing Field Guard"},
        files={
            "file": (
                "missing-field.txt",
                b"Object: {{project.name}}\nApproved by: {{manual.approved_by}}",
                "text/plain",
            )
        },
    )
    assert upload_resp.status_code == 201, upload_resp.text
    template_id = upload_resp.json()["id"]

    render_resp = client.post(
        f"/api/v1/admin/documents/projects/{project_id}/render",
        json={"template_id": template_id, "overrides": {}},
    )
    assert render_resp.status_code == 422, render_resp.text
    error = render_resp.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["message"] == "Document template has unresolved placeholders"
    assert error["meta"]["missing_placeholders"] == ["manual.approved_by"]


def test_installer_cannot_access_admin_documents(client_installer):
    resp = client_installer.get("/api/v1/admin/documents/templates")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"
