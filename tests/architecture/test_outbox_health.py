import json
import os
import time

import pytest

from app.workers import outbox_health, outbox_worker


@pytest.fixture()
def marker(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.json"
    monkeypatch.setattr(outbox_health, "heartbeat_path", lambda: path)
    return path


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
    def fail(**kwargs):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(outbox_worker, "run_once", fail)
    with pytest.raises(RuntimeError):
        outbox_worker.main()
    assert not marker.exists()


def test_idle_committed_pass_refreshes_health(marker, monkeypatch):
    monkeypatch.setattr(outbox_worker, "run_once", lambda **kwargs: 0)
    def stop(seconds):
        assert seconds == 3 and outbox_health.healthy()
        raise InterruptedError()
    monkeypatch.setattr(outbox_worker.time, "sleep", stop)
    with pytest.raises(InterruptedError):
        outbox_worker.main()
