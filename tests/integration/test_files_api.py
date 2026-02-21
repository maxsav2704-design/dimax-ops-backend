from __future__ import annotations

import uuid
from urllib.parse import urlparse

from app.modules.files.infrastructure.models import FileDownloadEventORM
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
            "title": "Files Journal",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_admin_files_downloads_list_and_filter(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Files Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)

    pdf_resp = client_admin_real_uow.get(f"/api/v1/admin/journals/{journal_id}/pdf")
    assert pdf_resp.status_code == 200, pdf_resp.text

    list_resp = client_admin_real_uow.get(
        f"/api/v1/admin/files/downloads?journal_id={journal_id}&limit=10"
    )
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()["items"]
    assert len(items) >= 1
    assert any(
        item["source"] == "ADMIN"
        and item["correlation_id"] == journal_id
        and item["file_name"] == f"journal_{journal_id}.pdf"
        for item in items
    )


def test_public_file_download_by_token_consumes_usage(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Public Files Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)

    share_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/pdf/share",
        json={
            "ttl_sec": 300,
            "uses": 1,
            "audience": "+15550004444",
        },
    )
    assert share_resp.status_code == 200, share_resp.text
    share_body = share_resp.json()

    parsed = urlparse(share_body["url"])
    path_with_query = parsed.path
    if parsed.query:
        path_with_query = f"{path_with_query}?{parsed.query}"

    first_dl_resp = client_admin_real_uow.get(path_with_query)
    assert first_dl_resp.status_code == 200, first_dl_resp.text
    assert first_dl_resp.content[:4] == b"%PDF"

    second_dl_resp = client_admin_real_uow.get(path_with_query)
    assert second_dl_resp.status_code == 403, second_dl_resp.text
    assert second_dl_resp.json()["error"]["code"] == "FORBIDDEN"

    token = parsed.path.rsplit("/", 1)[-1]
    event = (
        db_session.query(FileDownloadEventORM)
        .filter(
            FileDownloadEventORM.company_id == company_id,
            FileDownloadEventORM.source == "PUBLIC_TOKEN",
            FileDownloadEventORM.token == token,
        )
        .order_by(FileDownloadEventORM.created_at.desc())
        .first()
    )
    assert event is not None


def test_admin_files_endpoints_forbidden_for_installer(client_installer):
    resp = client_installer.get("/api/v1/admin/files/downloads")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"
