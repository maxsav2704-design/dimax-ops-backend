"""Do not report uncommitted delivery or continue a batch after rollback."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.modules.outbox.domain.enums import OutboxChannel
from app.workers import outbox_health, outbox_worker


@pytest.mark.parametrize("fail_on,send_error,expected_sent,expected_attempts", [
    (1, False, 0, 1),
    (2, False, 1, 2),
    (1, True, 0, 1),
    (None, False, 3, 3),
])
def test_worker_counts_only_committed_jobs_and_stops_after_commit_error(
    monkeypatch, tmp_path, fail_on, send_error, expected_sent, expected_attempts
):
    monkeypatch.setattr(outbox_health, "heartbeat_path", lambda: tmp_path / "heartbeat.json")
    session = MagicMock()
    commits = 0

    def commit():
        nonlocal commits
        commits += 1
        if commits == fail_on:
            raise RuntimeError("Synthetic commit failure")
        if commits <= len(messages):
            messages[commits - 1]._expired = True

    session.commit.side_effect = commit
    repo = MagicMock()

    class ExpiringMessage(SimpleNamespace):
        def __getattribute__(self, name):
            if name != "__dict__" and super().__getattribute__("__dict__").get("_expired"):
                raise AssertionError("Logging must not reload committed ORM rows")
            return super().__getattribute__(name)

    messages = [ExpiringMessage(
        id=uuid4(), company_id=uuid4(), correlation_id=None, channel=OutboxChannel.EMAIL,
        attempts=0, max_attempts=5,
        payload={"to_email": "test@dimax.example", "subject": "TEST", "body_text": "Synthetic"},
    ) for _ in range(3)]
    repo.lock_next_batch.side_effect = [[message] for message in messages] + [[]]
    sender = MagicMock()
    if send_error:
        sender.send.side_effect = ConnectionRefusedError("Synthetic SMTP outage")
    log = MagicMock()
    monkeypatch.setattr(outbox_worker, "SessionLocal", lambda: session)
    monkeypatch.setattr(outbox_worker, "OutboxRepository", lambda current: repo)
    monkeypatch.setattr(outbox_worker, "email_sender", sender)
    monkeypatch.setattr(outbox_worker, "log_event", log)

    assert outbox_worker.run_once() == expected_sent
    assert sender.send.call_count == expected_attempts
    events = [call.args[1] for call in log.call_args_list]
    assert events.count("outbox.message.sent") == expected_sent
    assert events.count("outbox.message.commit_failed") == int(fail_on is not None)
    if fail_on is not None:
        session.rollback.assert_called_once()
        assert commits == fail_on
        assert "outbox.batch.completed" not in events
    else:
        session.rollback.assert_not_called()
    session.close.assert_called_once()
