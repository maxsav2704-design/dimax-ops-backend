from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.core.config import settings
from app.modules.journal.application.signing_links import journal_signing_url
from app.modules.journal.domain.enums import JournalStatus
from app.modules.settings.application.admin_service import SettingsAdminService


NOW = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)


def journal(**overrides):
    return SimpleNamespace(**{
        "id": uuid4(), "project_id": uuid4(), "title": "Acceptance",
        "status": JournalStatus.ACTIVE, "signed_at": None,
        "public_token": "test-token", "public_token_expires_at": NOW + timedelta(days=1),
        **overrides,
    })


@pytest.mark.parametrize("base", ["https://app.example.com", "https://app.example.com/ops/"])
def test_signing_link_uses_human_app_not_api_origin(monkeypatch, base):
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", base)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://api.example.com")
    assert journal_signing_url(journal(), now=NOW) == f"{base.rstrip('/')}/acceptance/test-token"


@pytest.mark.parametrize("overrides", [
    {"status": JournalStatus.DRAFT},
    {"status": JournalStatus.ARCHIVED},
    {"signed_at": NOW},
    {"public_token": None},
    {"public_token": ""},
    {"public_token_expires_at": NOW},
    {"public_token_expires_at": NOW - timedelta(seconds=1)},
])
def test_unusable_signing_link_is_omitted(overrides):
    assert journal_signing_url(journal(**overrides), now=NOW) is None


def test_legacy_unexpired_token_and_path_encoding(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://app.example.com/")
    assert journal_signing_url(
        journal(public_token="part/with?fragment#", public_token_expires_at=None), now=NOW
    ) == "https://app.example.com/acceptance/part%2Fwith%3Ffragment%23"


@pytest.mark.parametrize("status", [JournalStatus.DRAFT, JournalStatus.ACTIVE, JournalStatus.ARCHIVED])
def test_template_variables_follow_same_link_lifecycle(monkeypatch, status):
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://app.example.com/")
    row = journal(status=status, public_token_expires_at=None)
    uow = Mock()
    uow.journals.get.return_value = row
    uow.projects.get.return_value = SimpleNamespace(name="Site", address="Site address")
    monkeypatch.setattr(SettingsAdminService, "get_company", Mock(return_value=SimpleNamespace(name="QA")))
    variables = SettingsAdminService.build_template_variables(uow, company_id=uuid4(), journal_id=row.id)
    expected = "https://app.example.com/acceptance/test-token" if status == JournalStatus.ACTIVE else None
    assert variables["public_url"] == expected
    assert SettingsAdminService._render_text("Review {{public_url}}", variables) == f"Review {expected or ''}"
