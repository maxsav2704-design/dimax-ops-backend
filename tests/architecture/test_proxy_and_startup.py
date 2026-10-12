import asyncio
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.v1 import rate_limit
from app.core.runtime_guard import validate_startup
from app.shared.domain.errors import TooManyRequests


def invoke(peer, forwarded, *, trusted="172.30.254.2"):
    async def endpoint(scope, receive, send):
        request = Request(scope)
        rate_limit.rate_limit_auth_login(request)
        return request.client.host, scope["scheme"]

    scope = {"type": "http", "scheme": "http", "client": (peer, 1234),
             "headers": [(b"x-forwarded-for", forwarded.encode()), (b"x-forwarded-proto", b"https")]}
    return asyncio.run(ProxyHeadersMiddleware(endpoint, trusted_hosts=trusted)(scope, None, None))


def test_proxy_clients_have_independent_login_buckets(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "AUTH_LOGIN_RL_MAX_REQ", 2)
    assert invoke("172.30.254.2", "198.51.100.11") == ("198.51.100.11", "https")
    invoke("172.30.254.2", "198.51.100.11")
    with pytest.raises(TooManyRequests):
        invoke("172.30.254.2", "198.51.100.11")
    assert invoke("172.30.254.2", "198.51.100.12")[0] == "198.51.100.12"


def test_untrusted_peer_cannot_rotate_forwarded_ips_to_bypass_limit(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "AUTH_LOGIN_RL_MAX_REQ", 1)
    assert invoke("172.30.254.3", "198.51.100.11") == ("172.30.254.3", "http")
    with pytest.raises(TooManyRequests):
        invoke("172.30.254.3", "198.51.100.12")


def test_proxy_chain_uses_last_untrusted_address_not_attacker_prefix():
    assert invoke("172.30.254.2", "192.0.2.99, 198.51.100.11")[0] == "198.51.100.11"


def test_direct_production_start_rejects_unsafe_settings_without_printing_values(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    secret = "unsafe-value-do-not-echo"
    with pytest.raises(RuntimeError) as caught:
        validate_startup(SimpleNamespace(model_dump=lambda: {"JWT_SECRET": secret}))
    assert secret not in str(caught.value)
    assert "JWT_SECRET" in str(caught.value)


def test_test_mode_does_not_require_real_production_credentials(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    assert validate_startup(SimpleNamespace(model_dump=lambda: {})) is False


def test_direct_production_start_accepts_effective_settings_and_hides_docs(monkeypatch):
    from pydantic import SecretStr
    from app import main
    from app.core.config import Settings
    from test_production_env_contract import _valid_env

    env = _valid_env()
    monkeypatch.setattr(main, "settings", Settings(_env_file=None, **env))
    monkeypatch.setattr(main.email_settings, "FACTORY_APPROVAL_EMAIL_KEY", SecretStr(env["FACTORY_APPROVAL_EMAIL_KEY"]))
    monkeypatch.setenv("APP_ENV", "production")
    app = main.create_app()
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None
