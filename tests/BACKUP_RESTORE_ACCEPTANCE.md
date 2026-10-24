# Safe backup/restore rehearsal: 2026-10-24

## Current result

**Synthetic PostgreSQL recovery checks passed; cleanup independently confirmed;
20 safety unit tests passed. Full application recovery is NOT established.**

The October 24 continuation first verified the ordinary API at both /health and
/ready (HTTP 200, database ready). No API restart, database restart, migration or
working-data query was needed. Previous HTTP timeouts were not reproduced at the
start of this session; memory pressure was observed, but is not a proven exclusive
cause of those timeouts.

With the user's permission, only the five ordinary DIMAX workers were paused.
The API, database and MinIO stayed running. At 369 MiB available host RAM the
isolated runner started PostgreSQL 16.12 with a 128 MiB limit. A runtime sample
showed 49.58 MiB used. No other test service, external network, host mount or
working volume was involved. The original workers are restored after the check.

Run ID: `28b0a7ddd3d74cacb0fa7b811137737f`. Real checks passed:

- pg_dump/pg_restore round trip, matching rows, selected schema metadata and
  sequence state;
- refusal to overwrite the source, an existing archive or an existing target;
- rejection of a deliberately damaged archive;
- rejection of a deliberately changed restored amount;
- unchanged source and removal of temporary targets/dumps after both failures;
- second successful restore, with total earnings still 21.50 and exactly one
  pending outbox record. No worker processed these synthetic messages.

Verified archive hashes (temporary archives removed):
`ea1a7cdec0ff8a9c05b8891351603a228e1440342f23972581f592aaa9786ef9`
and `4f5e3cfef6087e7eba0bb66fb753f4c26c23ad9d46101efd484ccad5b04f5108`.

The first complete data run exited 1 at the final absence check, AFTER removing
its resources: Docker returned `get <name>: no such volume`, while the checker
only recognized `no such volume: <name>`. The checker now accepts those two
explicit missing-volume responses for the exact requested name. Other errors,
including daemon failures or another volume's name, still fail closed.
Two regression tests were added; all 20 tests passed in 0.273 seconds.

After this correction, a separate real-Docker invocation of owned_container and
owned_volume for this exact run confirmed both resources absent and exited 0.
This is a combined data-run plus cleanup-recheck acceptance, not a claim that
the entire corrected runner has been rerun with exit 0. Available RAM was then
54 MiB, so a new complete run was not started and the 256 MiB guard was unchanged.

Earlier preparation found and fixed a readiness race with the image's temporary
Unix-socket initialization server. The successful real data run above validates
waiting for the final TCP listener. Earlier low-memory refusals and the initial
seed failure remain historical failed attempts, not successful restores.

This procedure temporarily fits a small fixture onto this memory-constrained
machine; it does not resolve the machine's sustained capacity shortage. Do not
start a full-stack acceptance environment on the basis of this result.

## Operational handback

Restoring the workers initially hit `resource temporarily unavailable` on outbox,
leaving outbox and maintenance stopped. A host HTTP probe also timed out during
this pressure. The API/database/MinIO containers were never restarted.

Read-only WSL inspection showed 795252 KiB Cached (about 777 MiB), 0 KiB Dirty,
and 933468 KiB MemAvailable inside the VM, while Windows had very little free RAM.
One explicit diagnostic `sysctl -w vm.drop_caches=1` in docker-desktop released
clean WSL page cache, without removing files, changing persistent WSL settings,
or restarting Docker. This is a one-off cache operation, not a scheduled fix or
a change to application/database settings. Cache rebuilding can temporarily add
I/O; do not automate repeated cache dropping. See the
[Microsoft WSL memory-reclaim explanation](https://devblogs.microsoft.com/commandline/memory-reclaim-in-the-windows-subsystem-for-linux-2/)
and [kernel guidance](https://www.kernel.org/doc/html/v6.12/admin-guide/sysctl/vm.html#drop-caches).

After that operation and the user's closure of unnecessary applications, Windows
reported 294 MiB available. The individual contribution of each action was not
measured. Starting the original outbox and maintenance containers then succeeded.
Final docker ps confirmed all five original workers running and the unchanged API
and database healthy; MinIO was still running. Both host /health and /ready
returned HTTP 200, with database ready, after all five workers were restored.
No test container or volume remains. Do not interpret a recovered local session
as evidence that 4 GiB RAM is sufficient for sustained full-stack operation.

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
No queue worker is launched. The checks are:

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
Docker daemon during cleanup inspection, supported missing-volume diagnostics,
wrong-volume diagnostics, final-server readiness and readiness timeout.
Tests create only private temporary files.

## Remaining release gates

- On a host with stable memory headroom, rerun the complete corrected runner to
  obtain one uninterrupted exit-0 result (data and cleanup separately passed here).
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
