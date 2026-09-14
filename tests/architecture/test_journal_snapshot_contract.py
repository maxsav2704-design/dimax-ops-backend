from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.deps import get_current_user, get_uow
from app.modules.journal.api.admin import router
from app.modules.journal.api.schemas import JournalAdminSnapshotResponse, PublicJournalGetResponse
from app.modules.journal.application.admin_service import JournalAdminService
from app.modules.journal.application.public_api_service import JournalPublicApiService
from app.modules.journal.application.use_cases import JournalUseCases
from app.modules.journal.domain.enums import JournalStatus
from app.shared.domain.errors import ForbiddenScope, NotFound


@pytest.fixture
def snapshot_data():
    now = datetime.now(timezone.utc)
    journal = SimpleNamespace(
        id=uuid4(), company_id=uuid4(), project_id=uuid4(), status=JournalStatus.DRAFT,
        title="Stored journal", notes="Stored notes", snapshot_version=4,
        lock_header=False, lock_table=True, lock_footer=False,
        signed_at=None, signer_name=None, public_token="test-token",
        public_token_expires_at=now + timedelta(days=1),
    )
    door_type_id = uuid4()
    uow = Mock()
    uow.journals.get.return_value = journal
    uow.journals.list_items.return_value = [SimpleNamespace(
        unit_label="A-01", door_type_id=door_type_id, installed_at=now,
    )]
    uow.journals.list_addon_items.return_value = [SimpleNamespace(
        addon_name="Adjustment", qty_done=Decimal("2.50"), unit="unit", done_at=now, comment=None,
    )]
    uow.projects.get.return_value = SimpleNamespace(
        name="Stored site", address=None, developer_company="Developer", contact_name=None,
    )
    uow.door_types.list_active.return_value = [SimpleNamespace(id=door_type_id, name="Entrance")]
    return uow, journal


def test_snapshot_uses_only_scoped_stored_work(snapshot_data):
    uow, journal = snapshot_data
    result = JournalAdminService.get_snapshot(uow, company_id=journal.company_id, journal_id=journal.id)
    JournalAdminSnapshotResponse.model_validate(result)
    assert result["journal"]["snapshot_version"] == 4
    assert result["items"][0]["unit_label"] == "A-01"
    assert result["addon_items"][0]["quantity"] == "2.50"
    assert result["signing_url"] is None
    scope = {"company_id": journal.company_id, "journal_id": journal.id}
    uow.journals.get.assert_called_once_with(**scope)
    uow.journals.list_items.assert_called_once_with(**scope)
    uow.journals.list_addon_items.assert_called_once_with(**scope)
    uow.doors.list_by_project.assert_not_called()
    uow.journals.save.assert_not_called()


def test_foreign_or_missing_journal_stops_before_snapshot_reads(snapshot_data):
    uow, journal = snapshot_data
    uow.journals.get.return_value = None
    foreign_company = uuid4()
    with pytest.raises(NotFound):
        JournalAdminService.get_snapshot(uow, company_id=foreign_company, journal_id=journal.id)
    uow.journals.get.assert_called_once_with(company_id=foreign_company, journal_id=journal.id)
    uow.journals.list_items.assert_not_called()
    uow.projects.get.assert_not_called()


@pytest.mark.parametrize("status,expired,signed,has_link", [
    (JournalStatus.DRAFT, False, False, False),
    (JournalStatus.ACTIVE, False, False, True),
    (JournalStatus.ACTIVE, True, False, False),
    (JournalStatus.ARCHIVED, False, True, False),
])
def test_snapshot_signing_link_respects_lifecycle(snapshot_data, status, expired, signed, has_link):
    uow, journal = snapshot_data
    journal.status = status
    if expired:
        journal.public_token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    if signed:
        journal.signed_at = datetime.now(timezone.utc)
    result = JournalAdminService.get_snapshot(uow, company_id=journal.company_id, journal_id=journal.id)
    assert bool(result["signing_url"]) is has_link


def test_public_and_admin_snapshot_content_remains_identical(snapshot_data, monkeypatch):
    uow, journal = snapshot_data
    public_get = Mock(return_value=journal)
    monkeypatch.setattr(JournalUseCases, "public_get", public_get)
    public = JournalPublicApiService.public_get(uow, token="authorized-token")
    admin = JournalAdminService.get_snapshot(uow, company_id=journal.company_id, journal_id=journal.id)
    admin.pop("signing_url")
    assert public == admin
    PublicJournalGetResponse.model_validate(public)
    public_get.assert_called_once_with(uow, token="authorized-token")


@pytest.mark.parametrize("role,scope,allowed", [
    ("ADMIN", "OWNER", True), ("ADMIN", "OPERATIONS", True),
    ("ADMIN", "VIEWER", True), ("INSTALLER", None, False),
])
def test_snapshot_route_keeps_admin_authorization(snapshot_data, monkeypatch, role, scope, allowed):
    uow, journal = snapshot_data
    response_body = JournalAdminService.get_snapshot(uow, company_id=journal.company_id, journal_id=journal.id)
    service = Mock(return_value=response_body)
    monkeypatch.setattr(JournalAdminService, "get_snapshot", service)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        role=role, admin_scope=scope, company_id=journal.company_id,
    )
    unit = nullcontext()
    app.dependency_overrides[get_uow] = lambda: unit
    with TestClient(app) as client:
        if not allowed:
            with pytest.raises(ForbiddenScope):
                client.get(f"/api/v1/admin/journals/{journal.id}/snapshot")
            service.assert_not_called()
        else:
            response = client.get(f"/api/v1/admin/journals/{journal.id}/snapshot")
            assert response.status_code == 200
            service.assert_called_once_with(unit, company_id=journal.company_id, journal_id=journal.id)
