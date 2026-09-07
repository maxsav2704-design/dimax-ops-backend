from __future__ import annotations

from typing import Any

from app.modules.files.infrastructure.repositories import FileTokenRepository
from app.modules.journal.infrastructure.models import JournalSignatureORM
from app.modules.journal.infrastructure.repositories import JournalRepository


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


def test_public_file_token_consumption_locks_the_token_row() -> None:
    query = _QuerySpy()
    repository = FileTokenRepository(_SessionSpy(query))  # type: ignore[arg-type]

    repository.get_by_token("one-time-public-token")

    assert query.for_update_calls == 1


def test_public_journal_signature_locks_the_journal_row() -> None:
    query = _QuerySpy()
    repository = JournalRepository(_SessionSpy(query))  # type: ignore[arg-type]

    repository.get_by_token(token="public-journal-token", for_update=True)

    assert query.for_update_calls == 1


def test_journal_signature_is_unique_by_journal_id() -> None:
    constraint = next(
        item
        for item in JournalSignatureORM.__table__.constraints
        if item.name == "uq_journal_signatures_one_per_journal"
    )

    assert [column.name for column in constraint.columns] == ["journal_id"]
