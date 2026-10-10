"""Process liveness after a committed queue pass, not proof of mail delivery."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

MAX_AGE_SECONDS = 600  # A batch can include twenty SMTP calls with 20s timeouts.


def heartbeat_path() -> Path:
    return Path(tempfile.gettempdir()) / "dimax-outbox-heartbeat.json"


def record_heartbeat() -> None:
    target = heartbeat_path()
    temporary = target.with_suffix(f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps({"pid": os.getpid(), "completed_at": time.monotonic()}), encoding="ascii")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def healthy() -> bool:
    try:
        record = json.loads(heartbeat_path().read_text(encoding="ascii"))
        pid, completed = record["pid"], record["completed_at"]
        if type(pid) is not int or pid <= 0 or type(completed) not in (int, float):
            return False
        if not 0 <= time.monotonic() - completed <= MAX_AGE_SECONDS:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
