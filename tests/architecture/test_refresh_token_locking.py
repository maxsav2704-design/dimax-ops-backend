from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.modules.identity.infrastructure.refresh_tokens_repo import (
    RefreshTokenRepository,
)


class _QuerySpy:
    def __init__(self) -> None:
        self.for_update_calls = 0

    def filter(self, *args: Any) -> _QuerySpy:
        return self

    def with_for_update(self) -> _QuerySpy:
        self.for_update_calls += 1
        return self

    def one_or_none(self) -> None:
        return None


class _SessionSpy:
    def __init__(self, query: _QuerySpy) -> None:
        self.query_spy = query

    def query(self, *args: Any) -> _QuerySpy:
        return self.query_spy


def test_refresh_rotation_and_logout_lock_the_session_row() -> None:
    query = _QuerySpy()
    repository = RefreshTokenRepository(_SessionSpy(query))  # type: ignore[arg-type]
    company_id = uuid4()

    repository.get_by_jti(company_id=company_id, jti="rotation-jti")
    repository.get_active_by_jti(company_id=company_id, jti="logout-jti")

    assert query.for_update_calls == 2
