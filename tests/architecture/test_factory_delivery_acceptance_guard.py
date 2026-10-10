from unittest.mock import MagicMock

import pytest

from scripts.factory_delivery_acceptance import guard, request, settings


@pytest.fixture()
def disposable(monkeypatch):
    monkeypatch.setenv("DIMAX_FACTORY_DELIVERY_CHECK", "1")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://postgres:postgres@db:5432/dimax_factory_delivery_0123456789ab")
    monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "mailpit")
    monkeypatch.setattr(settings, "SMTP_PORT", 1025)
    monkeypatch.setattr(settings, "WHATSAPP_ENABLED", False)
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://factory.example.test")


def test_explicit_disposable_delivery_environment_is_allowed(disposable):
    guard()


@pytest.mark.parametrize("key,value", [
    ("DATABASE_URL", "postgresql://postgres:postgres@db:5432/dimax_acceptance"),
    ("DATABASE_URL", "postgresql://postgres:postgres@remote:5432/dimax_factory_delivery_0123456789ab"),
    ("DATABASE_URL", "postgresql://postgres:postgres@db:5432/dimax_factory_delivery_"),
    ("SMTP_HOST", "smtp.example.com"), ("SMTP_PORT", 587), ("EMAIL_ENABLED", False),
    ("WHATSAPP_ENABLED", True), ("PUBLIC_APP_BASE_URL", "https://real.example.com"),
])
def test_real_services_or_non_disposable_database_are_rejected(disposable, monkeypatch, key, value):
    monkeypatch.setattr(settings, key, value)
    with pytest.raises(RuntimeError, match="disposable"):
        guard()


@pytest.mark.parametrize("key,value", [("APP_ENV", "production"), ("DIMAX_FACTORY_DELIVERY_CHECK", "0")])
def test_missing_explicit_test_opt_in_is_rejected(disposable, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="disposable"):
        guard()


def test_mailpit_cleanup_accepts_a_successful_plain_text_response(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = b"ok\n"
    monkeypatch.setattr("scripts.factory_delivery_acceptance.urlopen", lambda *a, **kw: response)
    assert request("http://mailpit:8025", "/api/v1/messages", {"IDs": ["owned-test-message"]},
                   method="DELETE", response_json=False) is None
