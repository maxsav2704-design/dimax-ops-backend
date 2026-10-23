# Safe backup/restore rehearsal: 2026-10-23

## Current result

**Tooling and safety unit tests complete; real PostgreSQL rehearsal NOT YET RUN.**
The first runtime attempt stopped before Docker because available host RAM was
below 256 MiB. A second attempt through a lighter shell also stopped before
Docker, with only 29 MiB available. No test container or volume was created by
either attempt, and working services were not stopped or restarted.

Sixteen standard-library tests passed in 0.239 seconds. They mock Docker and
database commands; they do not establish that pg_dump/pg_restore works. The first
sandboxed unit run encountered Windows temporary-directory permission errors;
the subsequent authorized normal-host run passed. Do not report a database
restore PASS until the runtime command below completes, including cleanup.

## Existing risks corrected

The old smoke script truncated an existing dump path, interpolated unchecked
database names into SQL, and dropped the requested target before creating it.
Its only validation was a nonzero public-table count.

The same script now:

- requires explicit Compose file/project coordinates or one explicit container;
- rejects invalid identifiers, identical source/target and system restore targets;
- creates a private dump exclusively, refusing an existing file or symlink;
- refuses an existing target, with createdb also guarding concurrent creation;
- restores into a newly created database using exit-on-error and one transaction,
  without --clean or an initial DROP DATABASE;
- compares every public base table's sorted row SHA256 fingerprints and counts,
  selected column/constraint/index/trigger/enum/sequence metadata and sequence state;
- verifies the archive SHA256 and rechecks that the source remained unchanged;
- deletes only the temporary dump it created and a target whose creation succeeded;
- fails visibly on cleanup failure instead of reporting success.

If createdb times out with an unknown outcome, the tool will not drop a database
whose ownership it cannot establish. In the isolated runner, the entire owned
container/volume can then be removed. Against another explicitly selected service,
inspect that uncertain target manually; do not rerun an old destructive script.

The CI backup job uses a dedicated explicit Compose project. The workspace helper
already supplies explicit coordinates. The script is a **rehearsal**, not a
scheduled backup producer: its own dump is temporary and removed even on failure.
Never point --dump-file at the only copy of a real backup (it now refuses it).

## Lightweight runtime procedure

From backend, with Docker available and enough free RAM:

```powershell
python -B scripts/test_backup_restore_acceptance.py --postgres-image sha256:97ff59a4e30e08d1c11bdcd9455e7832368c0572b576c9092cde2df4ae5552a3
```

This uses the cached PostgreSQL 16 image, never pulls/builds an image, and creates
one uniquely labelled container and one uniquely labelled temporary Docker volume.
The container has no network, no published ports, no host mounts, a read-only root,
128 MiB memory/no extra swap, 8 MiB shared buffers and eight maximum connections.
It mounts only its new volume and two small tmpfs directories. Host Python runs
the existing rehearsal tool; no API, application migrations, SMTP or MinIO starts.

Preflight refuses less than 256 MiB available host RAM or 512 MiB free temporary
disk space. This is a minimum for this tiny 128 MiB fixture, not a full-stack or
production capacity guarantee. It does not weaken the separate SMTP acceptance
runner's 1 GiB requirement. Never stop working services automatically to pass it.

The fixture is explicitly a **small synthetic schema**, not the current DIMAX
Alembic schema. It exercises two companies/projects, installed/pending doors,
exact decimal earnings and a correction (total 21.50), Hebrew/Russian text,
timestamps, binary signature markers, journal object references, JSON payloads,
pending/sent outbox records, foreign keys, uniqueness, indexes, enums and sequences.
No queue worker is launched. The intended checks are:

1. Real pg_dump/pg_restore round trip and complete fixture fingerprint equality.
2. Refusal to restore over the source, an existing archive or a sentinel database.
3. Rejection of a deliberately damaged synthetic archive.
4. Detection of a deliberately changed amount in the restored synthetic target.
5. Source integrity and removal of owned target/dump after both failures.
6. A repeated successful rehearsal with unchanged money and pending queue counts.
7. Label-verified removal of the owned container/volume. A Docker inspection error
   is not treated as successful cleanup. No prune or working-volume deletion.

## Safety tests

```powershell
python -B -m unittest discover -s tests -p test_backup_restore_safety.py -v
```

These cover dangerous arguments, missing/mixed context, existing files/databases,
dump/restore failures, unknown createdb timeout, fingerprint/archive mismatches,
cleanup failure, empty schema, low RAM, mutable image tags and an unavailable
Docker daemon during cleanup inspection. Tests create only private temporary files.

## Remaining release gates

- Run this runtime procedure after memory headroom is available; record the result.
- Rehearse the actual migrated application schema with synthetic business records
  on an isolated host with sufficient memory. Public-row and selected metadata
  checks here are not exhaustive verification of roles, grants, policies,
  extensions, routines, other schemas or large objects.
- Restore the document/object store independently and verify referenced PDF bytes.
  A PostgreSQL object_key is not a backup of its PDF; signature marker bytes in this
  fixture are not a signed customer document or PDF rendering acceptance.
- Define persistent encrypted off-machine backups, retention, credentials/key
  recovery, restore permissions, RPO/RTO and monitoring before real operation.
  Source-code backups in GitHub do not back up databases, PDFs or encryption keys.
- Use a quiescent source for fingerprint comparisons. This script does not hold
  one exported snapshot across concurrent live business writes, and is not a
  production cutover/point-in-time-recovery procedure.
