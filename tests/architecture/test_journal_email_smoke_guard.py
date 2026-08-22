from __future__ import annotations

import pytest

from app.scripts.smoke_journal_email_delivery import main


def test_journal_email_smoke_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(RuntimeError, match="restricted to non-production"):
        main()
