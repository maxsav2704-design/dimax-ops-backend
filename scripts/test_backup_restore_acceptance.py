"""One capped, network-isolated PostgreSQL container; no app services or live DBs."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

if __package__:
    from . import db_backup_restore_smoke as smoke
else:
    import db_backup_restore_smoke as smoke


LABEL = "dimax.restore-acceptance"


def free_memory_mib():
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in
                ("total", "available", "page_total", "page_free", "virtual_total", "virtual_free", "extended")]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise RuntimeError("Cannot determine available host RAM")
        return status.available / 1024**2
    values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return int(values["MemAvailable"].split()[0]) / 1024


def preflight(image):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("A cached immutable PostgreSQL image ID is required")
    available = free_memory_mib()
    if available < 256:
        raise RuntimeError(f"At least 256 MiB free host RAM required (available: {available:.0f} MiB); no resources created")
    if shutil.disk_usage(tempfile.gettempdir()).free < 512 * 1024**2:
        raise RuntimeError("At least 512 MiB free temporary disk space required")
    print(f"[restore-acceptance] free host RAM={available:.0f} MiB; PostgreSQL limit=128 MiB", flush=True)


def docker(*args, check=True, input=None):
    result = subprocess.run(["docker", *args], input=input, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=120, check=False)
    if check and result.returncode:
        raise RuntimeError(f"Isolated Docker operation failed: {args[0]} ({result.returncode})")
    return result


def owned_container(name, run_id):
    result = docker("container", "inspect", name, check=False)
    if result.returncode:
        if f"No such container: {name}" in result.stderr.decode(errors="replace"):
            return False
        raise RuntimeError("Cannot verify test container state; cleanup not confirmed")
    item = json.loads(result.stdout)[0]
    if item["Config"]["Labels"].get(LABEL) != run_id:
        raise RuntimeError("Container ownership mismatch; will not remove it")
    return True


def owned_volume(name, run_id):
    result = docker("volume", "inspect", name, check=False)
    if result.returncode:
        if f"no such volume: {name}" in result.stderr.decode(errors="replace").lower():
            return False
        raise RuntimeError("Cannot verify test volume state; cleanup not confirmed")
    if json.loads(result.stdout)[0].get("Labels", {}).get(LABEL) != run_id:
        raise RuntimeError("Volume ownership mismatch; will not remove it")
    return True


def expect_failure(action, text):
    try:
        action()
    except (ValueError, RuntimeError, FileExistsError) as error:
        if text not in str(error):
            raise
    else:
        raise AssertionError(f"Expected refusal: {text}")


def exercise(name, directory):
    args = SimpleNamespace(source_db="synthetic_source", restore_db="synthetic_restore",
                           db_user="postgres", service="db", container=name,
                           compose_file=None, project_name=None, dump_file=str(directory / "check.dump"))
    base = smoke._exec_base(args)
    seed = Path(__file__).with_name("fixtures").joinpath("restore_acceptance.sql").read_bytes()
    docker("exec", "-i", name, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
           "-U", "postgres", "-d", args.source_db, input=seed)
    original = smoke._snapshot(base, args, args.source_db)
    assert smoke.rehearse(args) == 0
    print("PASS: real pg_dump/pg_restore; data, schema and sequences match", flush=True)

    args.restore_db = args.source_db
    expect_failure(lambda: smoke.rehearse(args), "separate non-system")
    args.restore_db = "synthetic_restore"
    dump = Path(args.dump_file)
    dump.write_bytes(b"existing synthetic backup")
    expect_failure(lambda: smoke.rehearse(args), "")
    assert dump.read_bytes() == b"existing synthetic backup"
    dump.unlink()
    smoke._run(base + ["createdb", "-U", "postgres", "--", args.restore_db])
    smoke._query(base, args, args.restore_db, "CREATE TABLE sentinel(value text); INSERT INTO sentinel VALUES ('KEEP')")
    expect_failure(lambda: smoke.rehearse(args), "already exists")
    assert smoke._query(base, args, args.restore_db, "SELECT value FROM sentinel").strip() == b"KEEP"
    smoke._run(base + ["dropdb", "-U", "postgres", "--", args.restore_db])
    print("PASS: source, existing archive and existing target protected", flush=True)

    real_run = smoke._run
    for defect in ("archive", "amount"):
        def fault(cmd, **kwargs):
            if "pg_restore" in cmd and defect == "archive":
                # Replace only this invocation's disposable synthetic archive.
                with dump.open("r+b") as archive:
                    archive.write(b"BROKEN")
            result = real_run(cmd, **kwargs)
            if "pg_restore" in cmd and defect == "amount":
                smoke._query(base, args, args.restore_db, "UPDATE completed_work SET amount=99.99 WHERE id=1")
            return result
        with patch.object(smoke, "_run", side_effect=fault):
            expect_failure(lambda: smoke.rehearse(args), "Database tool failed" if defect == "archive" else "fingerprint mismatch")
        assert not dump.exists()
        assert not smoke._query(base, args, "postgres", "SELECT 1 FROM pg_database WHERE datname='synthetic_restore'").strip()
        assert smoke._snapshot(base, args, args.source_db) == original
        print(f"PASS: {defect} corruption rejected; source intact; temporary target/dump removed", flush=True)
    assert smoke.rehearse(args) == 0
    assert smoke._query(base, args, args.source_db, "SELECT sum(amount) FROM completed_work").strip() == b"21.50"
    assert smoke._query(base, args, args.source_db, "SELECT count(*) FROM outbox_messages WHERE status='PENDING'").strip() == b"1"
    print("PASS: recovery repeatable; earnings 21.50 and one pending job unchanged", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-image", required=True)
    image = parser.parse_args().postgres_image
    preflight(image)
    docker("image", "inspect", image, "--format", "{{.Id}}")
    run_id = uuid4().hex
    name, volume = f"dimax-restore-db-{run_id}", f"dimax-restore-data-{run_id}"
    print(f"[restore-acceptance] owned container={name}; volume={volume}", flush=True)
    try:
        docker("volume", "create", "--label", f"{LABEL}={run_id}", volume)
        if not owned_volume(volume, run_id):
            raise RuntimeError("Volume ownership mismatch")
        docker("run", "-d", "--pull", "never", "--name", name, "--label", f"{LABEL}={run_id}",
               "--network", "none", "--read-only", "--user", "postgres", "--memory", "128m",
               "--memory-swap", "128m", "--pids-limit", "64", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=4m",
               "--tmpfs", "/var/run/postgresql:rw,noexec,nosuid,mode=1777,size=4m",
               "--mount", f"type=volume,source={volume},target=/var/lib/postgresql/data",
               "--env", "POSTGRES_DB=synthetic_source", "--env", "POSTGRES_PASSWORD=synthetic-local-only",
               "--env", "POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C",
               image, "postgres", "-c", "shared_buffers=8MB", "-c", "max_connections=8",
               "-c", "work_mem=1MB", "-c", "maintenance_work_mem=8MB")
        for _ in range(30):
            result = docker("exec", name, "pg_isready", "-U", "postgres", "-d", "synthetic_source", check=False)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Isolated PostgreSQL did not become ready")
        if not owned_container(name, run_id):
            raise RuntimeError("Container ownership mismatch")
        with tempfile.TemporaryDirectory(prefix="dimax-restore-") as temporary:
            exercise(name, Path(temporary))
    finally:
        if owned_container(name, run_id):
            docker("rm", "-f", name)
        if owned_volume(volume, run_id):
            docker("volume", "rm", volume)
    if owned_container(name, run_id) or owned_volume(volume, run_id):
        raise RuntimeError("Owned resources remain after cleanup")
    print("PASS: owned container and volume removed; no working services changed", flush=True)


if __name__ == "__main__":
    main()
