from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.v1.deps import CurrentUser, get_current_user, require_admin
from app.main import create_app


@pytest.mark.parametrize("scope", ["OPERATIONS", "FINANCE", "VIEWER"])
@pytest.mark.parametrize("method,path", [
    ("PATCH", "/company"), ("POST", "/integrations/test-email"),
    ("POST", "/integrations/test-whatsapp"), ("POST", "/communication-templates"),
    ("PATCH", "/communication-templates/00000000-0000-0000-0000-000000000001"),
    ("DELETE", "/communication-templates/00000000-0000-0000-0000-000000000001"),
])
def test_settings_mutations_reject_non_owner_before_side_effects(scope, method, path):
    app = create_app()
    user = CurrentUser(id=uuid4(), company_id=uuid4(), role="ADMIN", admin_scope=scope)
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        result = client.request(method, "/api/v1/admin/settings" + path, json={})
    assert result.status_code == 403, result.text


def test_owner_settings_and_operations_calendar_remain_allowed():
    for scope, path in (("OWNER", "/api/v1/admin/settings/company"), ("OPERATIONS", "/api/v1/admin/calendar/events")):
        user = CurrentUser(id=uuid4(), company_id=uuid4(), role="ADMIN", admin_scope=scope)
        request = Request({"type": "http", "method": "PATCH", "path": path, "headers": []})
        assert require_admin(request, user) is user
