import base64
from contextlib import contextmanager
from unittest.mock import patch

from pydantic import SecretStr

from app.core.config import settings
from app.modules.rates.application.approval_email import email_settings

TEST_CODE = "123456"
TEST_KEY = SecretStr(base64.b64encode(bytes(range(32))).decode())


@contextmanager
def mailbox_settings():
    with patch.object(settings, "EMAIL_ENABLED", True), \
            patch.object(email_settings, "FACTORY_APPROVAL_EMAIL_KEY", TEST_KEY), \
            patch("app.modules.rates.application.approval_verification.secrets.randbelow", return_value=123456):
        yield
