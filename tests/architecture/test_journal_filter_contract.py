from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.deps import get_uow, require_admin
from app.modules.journal.api.admin import router
from app.modules.journal.application.admin_service import JournalAdminService
from app.modules.journal.domain.enums import JournalStatus


@pytest.fixture
def journal_filter_client(monkeypatch):
    company_id = uuid4()
    uow = nullcontext()
    service = Mock(return_value={"items": []})
    monkeypatch.setattr(JournalAdminService, "list_journals", service)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(company_id=company_id)
    app.dependency_overrides[get_uow] = lambda: uow
    with TestClient(app) as client:
        yield client, service, company_id, uow


@pytest.mark.parametrize("status", [None, *JournalStatus])
def test_journal_filter_accepts_domain_status_and_preserves_company(journal_filter_client, status):
    client, service, company_id, uow = journal_filter_client
    params = {} if status is None else {"status": status.value}
    response = client.get("/api/v1/admin/journals", params=params)
    assert response.status_code == 200
    assert response.json() == {"items": []}
    service.assert_called_once_with(
        uow, company_id=company_id, status=status, limit=50, offset=0,
    )


@pytest.mark.parametrize("status", ["READY", "SIGNED", "unknown", ""])
def test_journal_filter_rejects_invalid_status_before_database(journal_filter_client, status):
    client, service, _, _ = journal_filter_client
    response = client.get("/api/v1/admin/journals", params={"status": status})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "status"]
    service.assert_not_called()
