"""Document import inbox: upload without a project, automatic matching, clean files imported by themselves,
the office decides the rest; folder and mailbox feeders; tenancy and policy."""
from __future__ import annotations

import email.message
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from test_project_file_import_api import _create_door_type, _create_project, _xlsx_bytes
from app.api.v1.deps import CurrentUser, require_admin
from app.core.config import settings
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.projects.infrastructure.models import ImportInboxItemORM
from app.workers import import_inbox_worker

HEADERS = ["order_number", "house", "floor", "apartment", "location", "marking", "door_type", "qty", "price"]
INBOX = "/api/v1/admin/projects/import-inbox"


def workbook(order: str, rows: int = 2, *, bad=False):
    data = [[order, "A", 1, 100 + i, "dira", f"{order}-{100 + i}", "entrance", 1 if not (bad and i == 0) else 1.5, 500] for i in range(rows)]
    return _xlsx_bytes(HEADERS, data)


def upload(client, name: str, content: bytes, project_id: str | None = None):
    data = {"project_id": project_id} if project_id else {}
    return client.post(INBOX, files={"file": (name, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, data=data)


def door_count(client, project_id: str) -> int:
    return len(client.get(f"/api/v1/admin/projects/{project_id}").json()["doors"])


def test_known_order_number_matches_the_project_and_imports_without_a_click(client_admin_real_uow, db_session, company_id):
    client = client_admin_real_uow
    project_id = _create_project(client, name="Inbox Tower")
    _create_door_type(client, code="entrance", name="Entrance")
    # The project already carries doors of order AZ-77 (an earlier import): the next factory file of that order is routed by itself.
    first = client.post(f"/api/v1/admin/projects/{project_id}/doors/import-upload", files={"file": ("first.xlsx", workbook("AZ-77", 1), "application/octet-stream")},
                        data={"create_missing_door_types": "true"})
    assert first.status_code == 200, first.text
    assert door_count(client, project_id) == 1

    second = workbook("AZ-77", 3)
    response = upload(client, "factory manifest 2.xlsx", second)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["status"] == "IMPORTED" and item["match_reason"] == "ORDER_NUMBER" and item["matched_project_id"] == project_id
    assert item["matched_project_name"] == "Inbox Tower" and item["analysis"]["errors"] == 0
    assert item["import_result"]["imported"] == 2 and item["import_result"]["skipped"] == 1  # the first door already existed
    assert door_count(client, project_id) == 3
    logs = db_session.scalars(select(AuditLogORM).where(AuditLogORM.entity_id == uuid.UUID(item["id"]))).all()
    assert [log.action for log in logs] == ["IMPORT_INBOX_RECEIVED", "IMPORT_INBOX_AUTO_IMPORTED"]

    # The same file again (from any channel) is one inbox item and no second import.
    again = upload(client, "factory manifest 2 (copy).xlsx", second)
    assert again.status_code == 201 and again.json()["id"] == item["id"]
    assert door_count(client, project_id) == 3
    listed = client.get(INBOX).json()
    assert listed["auto_commit"] is True and [x["id"] for x in listed["items"]][0] == item["id"]


def test_unknown_document_waits_for_a_project_and_then_imports(client_admin_real_uow):
    client = client_admin_real_uow
    _create_project(client, name="Alpha Site")
    beta = _create_project(client, name="Beta Site")
    _create_door_type(client, code="entrance", name="Entrance")
    response = upload(client, "something.xlsx", workbook("ZZ-1", 2))
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["status"] == "NEEDS_PROJECT" and item["matched_project_id"] is None and item["order_numbers"] == ["ZZ-1"]
    done = client.post(f"{INBOX}/{item['id']}/commit", json={"project_id": beta}).json()
    assert done["status"] == "IMPORTED" and done["match_reason"] == "MANUAL" and done["import_result"]["imported"] == 2
    assert door_count(client, beta) == 2
    # Decided items cannot be decided twice.
    assert client.post(f"{INBOX}/{item['id']}/commit", json={"project_id": beta}).status_code == 409
    assert client.post(f"{INBOX}/{item['id']}/dismiss").status_code == 409


def test_project_code_or_name_in_the_file_name_routes_the_document(client_admin_real_uow):
    client = client_admin_real_uow
    coded = client.post("/api/v1/admin/projects", json={"name": "Coded Project", "address": "Code st", "code": "BLDG7"}).json()["id"]
    _create_door_type(client, code="entrance", name="Entrance")
    by_code = upload(client, "manifest BLDG7 october.xlsx", workbook("NEW-1", 1)).json()
    assert by_code["status"] == "IMPORTED" and by_code["match_reason"] == "PROJECT_CODE" and by_code["matched_project_id"] == coded
    by_name = upload(client, "Coded Project doors.xlsx", workbook("NEW-2", 1)).json()
    assert by_name["match_reason"] == "PROJECT_NAME" and by_name["matched_project_id"] == coded
    assert door_count(client, coded) == 2


def test_row_errors_stop_the_automatic_import_and_the_office_allows_a_partial_one(client_admin_real_uow):
    client = client_admin_real_uow
    project_id = _create_project(client, name="Partial Site")
    _create_door_type(client, code="entrance", name="Entrance")
    response = upload(client, "with errors.xlsx", workbook("PR-1", 3, bad=True), project_id=project_id)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["status"] == "ANALYZED" and item["analysis"]["errors"] == 1 and item["import_result"] is None
    assert door_count(client, project_id) == 0
    refused = client.post(f"{INBOX}/{item['id']}/commit", json={}).json()
    assert refused["status"] == "ANALYZED" and door_count(client, project_id) == 0
    partial = client.post(f"{INBOX}/{item['id']}/commit", json={"allow_partial_import": True}).json()
    assert partial["status"] == "IMPORTED" and partial["import_result"]["imported"] == 2 and partial["import_result"]["errors"] == 1
    assert door_count(client, project_id) == 2


def test_policy_off_keeps_clean_files_waiting_and_only_the_owner_changes_it(client_admin_real_uow, admin_user):
    client = client_admin_real_uow
    project_id = _create_project(client, name="Policy Site")
    _create_door_type(client, code="entrance", name="Entrance")
    from dataclasses import replace
    owner = replace(admin_user, admin_scope="OWNER")  # require_admin supplies the scope from the admin profile in production
    client.app.dependency_overrides[require_admin] = lambda: owner
    assert client.put(f"{INBOX}/policy", json={"auto_commit": False}).json() == {"auto_commit": False}
    item = upload(client, "clean.xlsx", workbook("PL-1", 1), project_id=project_id).json()
    assert item["status"] == "ANALYZED" and door_count(client, project_id) == 0
    assert client.post(f"{INBOX}/{item['id']}/commit", json={}).json()["status"] == "IMPORTED"
    client.app.dependency_overrides[require_admin] = lambda: replace(admin_user, admin_scope="OPERATIONS")
    assert client.put(f"{INBOX}/policy", json={"auto_commit": True}).status_code == 403
    assert client.get(f"{INBOX}/policy").json() == {"auto_commit": False}
    client.app.dependency_overrides[require_admin] = lambda: owner
    assert client.put(f"{INBOX}/policy", json={"auto_commit": True}).status_code == 200


def test_unsupported_and_broken_files_are_recorded_not_lost(client_admin_real_uow):
    client = client_admin_real_uow
    assert upload(client, "photo.png", b"\x89PNG").status_code == 422
    broken = upload(client, "broken.xlsx", b"not a workbook").json()
    assert broken["status"] == "FAILED" and broken["error"]
    dismissed = client.post(f"{INBOX}/{broken['id']}/dismiss").json()
    assert dismissed["status"] == "DISMISSED"


def test_inbox_is_private_to_the_company(client_admin_real_uow, make_user, db_session):
    client = client_admin_real_uow
    project_id = _create_project(client, name="Tenant Site")
    _create_door_type(client, code="entrance", name="Entrance")
    item = upload(client, "tenant.xlsx", workbook("TN-1", 1), project_id=project_id).json()
    from app.modules.identity.domain.enums import UserRole
    from app.modules.identity.infrastructure.models import CompanyORM
    other_company = CompanyORM(name=f"Other {uuid.uuid4().hex[:6]}", is_active=True)
    db_session.add(other_company); db_session.commit()
    stranger = make_user(role=UserRole.ADMIN, company=other_company.id)
    client.app.dependency_overrides[require_admin] = lambda: CurrentUser(stranger.id, other_company.id, "ADMIN", "OWNER", True, True, True)
    assert client.get(INBOX).json()["items"] == []
    assert client.post(f"{INBOX}/{item['id']}/commit", json={}).status_code == 404


def test_folder_worker_ingests_dropped_files_per_company(client_admin_real_uow, company_id, tmp_path, monkeypatch):
    client = client_admin_real_uow
    project_id = _create_project(client, name="Folder Site")
    _create_door_type(client, code="entrance", name="Entrance")
    client.post(f"/api/v1/admin/projects/{project_id}/doors/import-upload", files={"file": ("seed.xlsx", workbook("FD-9", 1), "application/octet-stream")},
                data={"create_missing_door_types": "true"})
    company_dir = tmp_path / str(company_id)
    company_dir.mkdir()
    (company_dir / "factory FD-9 batch 2.xlsx").write_bytes(workbook("FD-9", 3))
    (company_dir / "notes.docx").write_bytes(b"ignored")
    (tmp_path / "orphan.xlsx").write_bytes(workbook("FD-9", 1))  # no company for the root without IMPORT_INBOX_COMPANY_ID
    monkeypatch.setattr(settings, "IMPORT_INBOX_COMPANY_ID", "")
    assert import_inbox_worker.ingest_folder(tmp_path) == 1
    assert (company_dir / "processed" / "factory FD-9 batch 2.xlsx").exists() and not (company_dir / "factory FD-9 batch 2.xlsx").exists()
    assert (company_dir / "notes.docx").exists() and (tmp_path / "orphan.xlsx").exists()
    items = client.get(INBOX).json()["items"]
    assert items[0]["source"] == "FOLDER" and items[0]["status"] == "IMPORTED" and items[0]["matched_project_id"] == project_id
    assert door_count(client, project_id) == 3
    assert import_inbox_worker.ingest_folder(tmp_path) == 0


class FakeFetcher:
    def __init__(self, messages):
        self.messages = messages
        self.seen = []

    def unseen(self):
        return [(uid, msg) for uid, msg in self.messages if uid not in self.seen]

    def mark_seen(self, uid):
        self.seen.append(uid)


def mail(sender: str, message_id: str, attachments: list[tuple[str, bytes]]):
    msg = email.message.EmailMessage()
    msg["From"] = sender
    msg["Message-ID"] = message_id
    msg.set_content("factory delivery")
    for name, content in attachments:
        msg.add_attachment(content, maintype="application", subtype="octet-stream", filename=name)
    return msg


def test_mailbox_feeder_takes_attachments_from_allowed_senders_only(client_admin_real_uow, company_id, monkeypatch):
    client = client_admin_real_uow
    project_id = _create_project(client, name="Mail Site")
    _create_door_type(client, code="entrance", name="Entrance")
    monkeypatch.setattr(settings, "IMPORT_INBOX_ALLOWED_SENDERS", "factory@example.com")
    fetcher = FakeFetcher([
        (b"1", mail("Factory <factory@example.com>", "<m1@example.com>", [("Mail Site doors.xlsx", workbook("ML-1", 2)), ("photo.jpg", b"\xff\xd8")])),
        (b"2", mail("spam@example.com", "<m2@example.com>", [("Mail Site doors.xlsx", workbook("ML-2", 2))])),
    ])
    assert import_inbox_worker.ingest_mailbox(fetcher, company_id=company_id) == 1
    assert fetcher.seen == [b"1", b"2"]
    items = client.get(INBOX).json()["items"]
    assert len(items) == 1 and items[0]["source"] == "EMAIL" and items[0]["source_ref"] == "<m1@example.com>"
    assert items[0]["status"] == "IMPORTED" and items[0]["match_reason"] == "PROJECT_NAME"
    assert door_count(client, project_id) == 2
