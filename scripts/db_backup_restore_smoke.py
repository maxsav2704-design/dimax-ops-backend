from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], *, stdin=None, stdout=None) -> None:
    proc = subprocess.run(
        cmd,
        stdin=stdin,
        stdout=stdout,
        stderr=subprocess.PIPE,
        text=False,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{stderr}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PostgreSQL backup/restore smoke for docker compose db service."
    )
    parser.add_argument("--service", default="db")
    parser.add_argument("--db-user", default="postgres")
    parser.add_argument("--source-db", default="dimax")
    parser.add_argument("--restore-db", default="dimax_restore_smoke")
    parser.add_argument(
        "--compose-file",
        default=os.getenv("BACKUP_RESTORE_COMPOSE_FILE"),
        help="Optional docker compose file path.",
    )
    parser.add_argument(
        "--project-name",
        default=os.getenv("BACKUP_RESTORE_COMPOSE_PROJECT"),
        help="Optional docker compose project name.",
    )
    parser.add_argument(
        "--dump-file",
        default=".tmp/backup_restore_smoke.dump",
        help="Host path for temporary dump artifact.",
    )
    return parser.parse_args()


def _compose_base_cmd(args: argparse.Namespace) -> list[str]:
    cmd = ["docker", "compose"]
    if args.compose_file:
        cmd.extend(["-f", args.compose_file])
    if args.project_name:
        cmd.extend(["-p", args.project_name])
    return cmd


def main() -> int:
    args = _parse_args()
    dump_path = Path(args.dump_file).resolve()
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    compose_cmd = _compose_base_cmd(args)

    print("[backup-restore] dumping source database...")
    with dump_path.open("wb") as out:
        _run(
            compose_cmd + [
                "exec",
                "-T",
                args.service,
                "pg_dump",
                "-U",
                args.db_user,
                "-d",
                args.source_db,
                "-Fc",
            ],
            stdout=out,
        )

    print("[backup-restore] recreating restore database...")
    _run(
        compose_cmd + [
            "exec",
            "-T",
            args.service,
            "psql",
            "-U",
            args.db_user,
            "-d",
            "postgres",
            "-c",
            f"DROP DATABASE IF EXISTS {args.restore_db};",
        ]
    )
    _run(
        compose_cmd + [
            "exec",
            "-T",
            args.service,
            "createdb",
            "-U",
            args.db_user,
            args.restore_db,
        ]
    )

    print("[backup-restore] restoring dump into restore database...")
    with dump_path.open("rb") as src:
        _run(
            compose_cmd + [
                "exec",
                "-T",
                args.service,
                "pg_restore",
                "-U",
                args.db_user,
                "-d",
                args.restore_db,
                "--clean",
                "--if-exists",
            ],
            stdin=src,
        )

    print("[backup-restore] validating restored schema...")
    result = subprocess.run(
        compose_cmd + [
            "exec",
            "-T",
            args.service,
            "psql",
            "-U",
            args.db_user,
            "-d",
            args.restore_db,
            "-tAc",
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "restore validation failed")
    table_count = int((result.stdout or "0").strip() or "0")
    if table_count <= 0:
        raise RuntimeError("restore validation failed: no public tables found")

    print("[backup-restore] cleanup restore database...")
    _run(
        compose_cmd + [
            "exec",
            "-T",
            args.service,
            "psql",
            "-U",
            args.db_user,
            "-d",
            "postgres",
            "-c",
            f"DROP DATABASE IF EXISTS {args.restore_db};",
        ]
    )

    try:
        dump_path.unlink(missing_ok=True)
    except Exception:
        pass

    print(f"[backup-restore] OK: restored tables={table_count}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[backup-restore] ERROR: {exc}")
        sys.exit(1)
