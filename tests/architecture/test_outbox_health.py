import json
import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers import outbox_health, outbox_worker
from app.modules.outbox.domain.enums import OutboxChannel


@pytest.fixture()
def marker(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.json"
    monkeypatch.setattr(outbox_health, "heartbeat_path", lambda: path)
    return path


@pytest.fixture()
def queue(monkeypatch):
    session, repo, sender = MagicMock(), MagicMock(), MagicMock()
    repo.lock_next_batch.return_value = []
    monkeypatch.setattr(outbox_worker, "SessionLocal", lambda: session)
    monkeypatch.setattr(outbox_worker, "OutboxRepository", lambda current: repo)
    monkeypatch.setattr(outbox_worker, "email_sender", sender)
    return SimpleNamespace(session=session, repo=repo, sender=sender)


def queued_email():
    return SimpleNamespace(
        id=uuid4(), company_id=uuid4(), correlation_id=None,
        channel=OutboxChannel.EMAIL, attempts=0, max_attempts=5,
        payload={"to_email": "test@dimax.example", "subject": "TEST", "body_text": "Synthetic"},
    )


def test_successful_pass_publishes_a_private_free_live_marker(marker):
    outbox_health.record_heartbeat()
    assert outbox_health.healthy()
    assert set(json.loads(marker.read_text())) == {"pid", "completed_at"}
    assert list(marker.parent.iterdir()) == [marker]


@pytest.mark.parametrize("record", [None, "invalid", [], {}, {"pid": -1, "completed_at": 0},
    {"pid": True, "completed_at": 0}, {"pid": os.getpid(), "completed_at": "now"},
    {"pid": os.getpid(), "completed_at": float("nan")},
    {"pid": 10**100, "completed_at": time.monotonic()},
    {"pid": os.getpid(), "completed_at": time.monotonic() - 601},
    {"pid": os.getpid(), "completed_at": time.monotonic() + 3600}])
def test_invalid_missing_stale_future_markers_are_unhealthy(marker, record):
    if record is not None:
        marker.write_text(record if isinstance(record, str) else json.dumps(record))
    assert not outbox_health.healthy()


def test_dead_process_marker_is_unhealthy(marker, monkeypatch):
    outbox_health.record_heartbeat()
    def missing(*args):
        raise ProcessLookupError()
    monkeypatch.setattr(outbox_health.os, "kill", missing)
    assert not outbox_health.healthy()


def test_failed_queue_pass_does_not_refresh_health(marker, monkeypatch):
    outbox_health.record_heartbeat()
    def fail(**kwargs):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(outbox_worker, "run_once", fail)
    with pytest.raises(RuntimeError):
        outbox_worker.main()
    assert not marker.exists()


def test_idle_committed_pass_refreshes_health(marker, queue, monkeypatch):
    def stop(seconds):
        assert seconds == 3 and outbox_health.healthy()
        raise InterruptedError()
    monkeypatch.setattr(outbox_worker.time, "sleep", stop)
    with pytest.raises(InterruptedError):
        outbox_worker.main()
    queue.session.commit.assert_called_once()


@pytest.mark.parametrize("fail_on,send_error,expected_sends", [(1, False, 1), (2, False, 2), (1, True, 1)])
def test_commit_failure_clears_previous_health_and_main_does_not_republish(
    marker, queue, monkeypatch, fail_on, send_error, expected_sends
):
    outbox_health.record_heartbeat()
    queue.repo.lock_next_batch.return_value = [queued_email(), queued_email(), queued_email()]
    queue.session.commit.side_effect = [None] * (fail_on - 1) + [RuntimeError("Synthetic DB failure")]
    if send_error:
        queue.sender.send.side_effect = ConnectionRefusedError("Synthetic SMTP outage")

    def stop(seconds):
        assert not outbox_health.healthy()
        raise InterruptedError()

    monkeypatch.setattr(outbox_worker.time, "sleep", stop)
    with pytest.raises(InterruptedError):
        outbox_worker.main()
    assert not marker.exists()
    assert queue.sender.send.call_count == expected_sends
    queue.session.close.assert_called_once()


@pytest.mark.parametrize("failure", ["query", "final_commit", "session"])
def test_database_failure_invalidates_previous_health(marker, queue, monkeypatch, failure):
    outbox_health.record_heartbeat()
    if failure == "session":
        monkeypatch.setattr(outbox_worker, "SessionLocal", MagicMock(side_effect=RuntimeError("Synthetic DB failure")))
    elif failure == "query":
        queue.repo.lock_next_batch.side_effect = RuntimeError("Synthetic DB failure")
    else:
        queue.session.commit.side_effect = RuntimeError("Synthetic DB failure")
    with pytest.raises(RuntimeError, match="Synthetic DB failure"):
        outbox_worker.main()
    assert not outbox_health.healthy()
    assert not marker.exists()


def test_smtp_outage_with_saved_retry_is_a_healthy_worker_pass(marker, queue, monkeypatch):
    queue.repo.lock_next_batch.return_value = [queued_email()]
    queue.sender.send.side_effect = ConnectionRefusedError("Synthetic SMTP outage")

    def stop(seconds):
        assert seconds == 3 and outbox_health.healthy()
        raise InterruptedError()

    monkeypatch.setattr(outbox_worker.time, "sleep", stop)
    with pytest.raises(InterruptedError):
        outbox_worker.main()
    queue.repo.mark_failed.assert_called_once()
    queue.repo.mark_sent.assert_not_called()
    assert queue.session.commit.call_count == 2


def test_health_recovers_only_after_a_committed_pass(marker, queue):
    outbox_health.record_heartbeat()
    queue.repo.lock_next_batch.return_value = [queued_email()]
    queue.session.commit.side_effect = RuntimeError("Synthetic DB failure")
    assert outbox_worker.run_once() == 0
    assert not outbox_health.healthy()
    queue.session.commit.side_effect = None
    queue.repo.lock_next_batch.return_value = []
    assert outbox_worker.run_once() == 0
    assert outbox_health.healthy()


def test_sent_message_publishes_health_after_commits(marker, queue, monkeypatch):
    queue.repo.lock_next_batch.return_value = [queued_email()]
    original_record = outbox_worker.record_heartbeat

    def record():
        assert queue.session.commit.call_count == 2
        original_record()

    def stop(seconds):
        assert seconds == 1 and outbox_health.healthy()
        raise InterruptedError()

    monkeypatch.setattr(outbox_worker, "record_heartbeat", record)
    monkeypatch.setattr(outbox_worker.time, "sleep", stop)
    with pytest.raises(InterruptedError):
        outbox_worker.main()
    queue.sender.send.assert_called_once()
    queue.repo.mark_failed.assert_not_called()


def test_heartbeat_write_failure_does_not_turn_sent_mail_into_a_failed_job(marker, queue, monkeypatch):
    outbox_health.record_heartbeat()
    queue.repo.lock_next_batch.return_value = [queued_email()]
    monkeypatch.setattr(outbox_worker, "record_heartbeat", MagicMock(side_effect=OSError("Synthetic disk failure")))
    with pytest.raises(OSError, match="Synthetic disk failure"):
        outbox_worker.main()
    assert not marker.exists()
    queue.sender.send.assert_called_once()
    queue.repo.mark_failed.assert_not_called()
    assert queue.session.commit.call_count == 2
