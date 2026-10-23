"""Non-overwriting restore rehearsal against an explicitly selected DB service."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def _run(cmd, *, stdin=None, stdout=None):
    result = subprocess.run(cmd, stdin=stdin, stdout=stdout or subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError(f"Database tool failed (exit {result.returncode}); no successful restore claimed")
    return result.stdout


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="db")
    parser.add_argument("--db-user", default="postgres")
    parser.add_argument("--source-db", default="dimax")
    parser.add_argument("--restore-db", default="dimax_restore_smoke")
    parser.add_argument("--compose-file", default=os.getenv("BACKUP_RESTORE_COMPOSE_FILE"))
    parser.add_argument("--project-name", default=os.getenv("BACKUP_RESTORE_COMPOSE_PROJECT"))
    parser.add_argument("--container", help="Explicit container instead of Compose coordinates")
    parser.add_argument("--dump-file", default=".tmp/backup_restore_smoke.dump")
    return parser.parse_args(argv)


def _validate(args):
    for value in (args.source_db, args.restore_db, args.db_user):
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
            raise ValueError("Database/user names must be simple lowercase PostgreSQL identifiers")
    if args.source_db == args.restore_db or args.restore_db in {"postgres", "template0", "template1"}:
        raise ValueError("Restore target must be a separate non-system database")
    if args.container:
        if args.compose_file or args.project_name or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]+", args.container):
            raise ValueError("Select either one explicit container or explicit Compose coordinates")
    elif not args.compose_file or not args.project_name:
        raise ValueError("Explicit --compose-file and --project-name are required")
    elif not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.project_name):
        raise ValueError("Invalid Compose project name")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", args.service):
        raise ValueError("Invalid Compose service name")


def _exec_base(args):
    environment = ["--env", "PGOPTIONS=-c timezone=UTC -c datestyle=ISO,YMD"]
    if args.container:
        return ["docker", "exec", "-i", *environment, args.container]
    return ["docker", "compose", "-f", args.compose_file, "-p", args.project_name,
            "exec", "-T", *environment, args.service]


def _query(base, args, database, sql, *, stdout=None):
    return _run(base + ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
                        "-U", args.db_user, "-d", database, "-c", sql], stdout=stdout)


def _digest_file(stream):
    stream.seek(0)
    digest = hashlib.sha256()
    lines = 0
    while chunk := stream.read(65536):
        digest.update(chunk)
        lines += chunk.count(b"\n")
    return digest.hexdigest(), lines


def _snapshot(base, args, database):
    tables = _query(base, args, database, """
        SELECT quote_ident(table_schema)||'.'||quote_ident(table_name)
        FROM information_schema.tables
        WHERE table_schema='public' AND table_type='BASE TABLE'
        ORDER BY table_schema, table_name
    """).decode().splitlines()
    if not tables:
        raise RuntimeError("No public tables found; cannot establish restore integrity")
    result = {}
    for table in tables:
        # Store only row hashes locally; sorting handles different physical row order.
        with tempfile.TemporaryFile() as hashes:
            _query(base, args, database, f"""
                SELECT encode(sha256(convert_to(row_to_json(t)::text,'UTF8')),'hex') AS h
                FROM {table} AS t ORDER BY h
            """, stdout=hashes)
            result[table] = _digest_file(hashes)
    metadata = [
        """SELECT row_to_json(c)::text FROM (
            SELECT table_name,column_name,ordinal_position,column_default,is_nullable,
                   data_type,udt_name,character_maximum_length,numeric_precision,numeric_scale,
                   is_identity,identity_generation,is_generated,generation_expression
            FROM information_schema.columns WHERE table_schema='public'
            ORDER BY table_name,ordinal_position) c""",
        """SELECT c.relname,con.conname,pg_get_constraintdef(con.oid),con.convalidated
            FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
            ORDER BY c.relname,con.conname""",
        """SELECT tablename,indexname,indexdef FROM pg_indexes
            WHERE schemaname='public' ORDER BY tablename,indexname""",
        """SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname""",
        """SELECT t.typname,e.enumsortorder,e.enumlabel FROM pg_type t
            JOIN pg_enum e ON e.enumtypid=t.oid JOIN pg_namespace n ON n.oid=t.typnamespace
            WHERE n.nspname='public' ORDER BY t.typname,e.enumsortorder""",
        """SELECT sequencename,start_value,min_value,max_value,increment_by,cycle,cache_size
            FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename""",
    ]
    for index, sql in enumerate(metadata):
        result[f"metadata:{index}"] = hashlib.sha256(_query(base, args, database, sql)).hexdigest()
    sequences = _query(base, args, database, """
        SELECT quote_ident(schemaname)||'.'||quote_ident(sequencename)
        FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename
    """).decode().splitlines()
    for sequence in sequences:
        result[f"sequence:{sequence}"] = _query(base, args, database, f"SELECT last_value,is_called FROM {sequence}")
    return result


def rehearse(args):
    _validate(args)  # Refuse dangerous arguments before Docker or file writes.
    base = _exec_base(args)
    dump_path = Path(args.dump_file).absolute()
    dump_created = target_created = False
    try:
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL also refuses an existing symlink; never truncate another backup.
        fd = os.open(dump_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        dump_created = True
        with os.fdopen(fd, "wb") as dump:
            if _query(base, args, "postgres", f"SELECT 1 FROM pg_database WHERE datname='{args.restore_db}'").strip():
                raise RuntimeError("Restore target already exists; it will not be modified")
            before = _snapshot(base, args, args.source_db)
            print("[backup-restore] dumping explicitly selected source", flush=True)
            _run(base + ["pg_dump", "-U", args.db_user, "-d", args.source_db, "-Fc"], stdout=dump)
        with dump_path.open("rb") as dump:
            archive_hash, _ = _digest_file(dump)
        # createdb refuses a concurrent creation too. Cleanup is enabled only on success.
        _run(base + ["createdb", "-U", args.db_user, "--template=template0", "--", args.restore_db])
        target_created = True
        print("[backup-restore] restoring into newly created target", flush=True)
        with dump_path.open("rb") as dump:
            _run(base + ["pg_restore", "-U", args.db_user, "-d", args.restore_db,
                         "--exit-on-error", "--single-transaction"], stdin=dump)
        with dump_path.open("rb") as dump:
            if _digest_file(dump)[0] != archive_hash:
                raise RuntimeError("Backup archive changed during verification")
        if before != _snapshot(base, args, args.restore_db):
            raise RuntimeError("Restored data/schema/sequence fingerprint mismatch")
        if before != _snapshot(base, args, args.source_db):
            raise RuntimeError("Source changed during rehearsal; use a quiescent isolated source")
        print(f"[backup-restore] verified archive SHA256={archive_hash}", flush=True)
    finally:
        try:
            if target_created:
                _run(base + ["dropdb", "-U", args.db_user, "--", args.restore_db])
        finally:
            if dump_created:
                dump_path.unlink()
    print("[backup-restore] OK: fingerprints match; owned target and temporary dump removed", flush=True)
    return 0


def main():
    return rehearse(_parse_args())


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[backup-restore] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
