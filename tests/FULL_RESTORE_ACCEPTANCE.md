# Full-schema and PDF recovery acceptance

## Scope

Only synthetic data, an internal Docker network, owned volumes, and immutable
local image IDs are accepted. No application ports, live volumes, dotenv files,
delivery workers, or production database coordinates are used.

The runner applies the complete Alembic chain to a fresh PostgreSQL database,
creates two synthetic companies and journal PDFs using the actual application
renderer (Hebrew and Russian), and records pending but unsent email jobs.
It dumps/restores the database, compares every public table and catalog
fingerprint, and verifies PDF references. It then stops PostgreSQL to reduce
memory use, backs up PDFs from MinIO, removes the original synthetic object
store and its volume, and restores into a fresh store. SHA256, size, MIME type,
PDF parsing and references must match; corruption and missing files must fail.

Cleanup verifies ownership labels before removal and fails closed on daemon
errors. Temporary source copies, PDFs and backups are removed at the end.
CI retains only a synthetic execution log for seven days.

## Commands

```sh
python -B -m unittest discover -s tests -p 'test_*restore_safety.py' -v
python -B scripts/test_full_restore_acceptance.py \
  --postgres-image sha256:<cached-image-id> \
  --app-image sha256:<cached-image-id> \
  --storage-image sha256:<cached-image-id>
```

Use the dedicated `Full Schema and PDF Recovery` workflow for sufficient RAM.
The local runner requires 768 MiB available RAM and 1 GiB free disk before
creating resources. On 2026-10-24 the local preflight refused to start because
only 67 MiB RAM was available. All five temporarily stopped normal DIMAX workers
were restored; normal health and readiness returned HTTP 200.

## Evidence status

2026-10-24: 27 safety unit tests passed. Remote full runtime pending.

## Limits

This verifies a quiescent synthetic backup, not an online coordinated backup
of production DB/storage. All public tables are compared, but only the seeded
journal/door/outbox subset contains business rows. Roles, grants, external
secrets, encryption keys, point-in-time recovery, remote backup retention and
production RTO/RPO remain separate operational acceptance tasks. PDF parsing
is not a visual layout review. No real signatures, prices or emails are used.
