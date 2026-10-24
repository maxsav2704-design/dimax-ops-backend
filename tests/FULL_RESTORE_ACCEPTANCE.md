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

2026-10-24: 27 safety unit tests passed locally and in CI. Full runtime PASSED:

- Run: https://github.com/maxsav2704-design/dimax-ops-backend/actions/runs/40077862961
- Tested code: `47049549a3b7937ce1f7d1df400c20e5c0f849f2`.
- Migration head: `0088_work_stages`; 73 public tables.
- Source and restored schema/data/sequence fingerprints matched.
- Two actual renderer PDFs (Hebrew/Russian) restored from the downloaded backup
  after the original synthetic MinIO container and volume were removed.
- PDF SHA256, length, MIME type, parser checks and journal references matched.
- Corrupt PDF, missing PDF and a weakened role CHECK were rejected. Original
  objects/constraint were restored and verified again.
- Pending synthetic email rows were preserved. No workers or external delivery
  ran in the test environment; resuming delivery after recovery is not tested.
- All owned containers, volumes, network and temporary files were removed.
- Runner available RAM: 14,764 MiB. Complete job: 3m18s including image builds;
  this small synthetic run is not evidence of production recovery time.
- Local workers restored; API `/health` and `/ready` returned HTTP 200 afterward.

The first two remote runs failed on CHECK-definition text differences, not data
loss. PostgreSQL distributes array casts when reparsing restored constraints.
The full probe now reparses each CHECK in a temporary table inside a rolled-back
savepoint before comparing it. It does not remove constraints from comparison,
rewrite application migrations, or normalize SQL using regex. A real weakening
to `CHECK (true)` is tested and rejected. The generic psql snapshot helper keeps
its stricter raw-definition comparison; this full probe supplies normalization
through its isolated direct-connection adapter.

## Limits

This verifies a quiescent synthetic backup, not an online coordinated backup
of production DB/storage. All public tables are compared, but only the seeded
journal/door/outbox subset contains business rows. Roles, grants, external
secrets, encryption keys, point-in-time recovery, remote backup retention and
production RTO/RPO remain separate operational acceptance tasks. PDF parsing
is not a visual layout review. No real signatures, prices or emails are used.
