# Restored outbox acceptance

## Scope and isolation

This extends the full-schema/PDF rehearsal, not a production restore command.
It uses fresh PostgreSQL databases on an internal Docker network, fresh MinIO
volumes, synthetic companies and signed journals, two synthetic historical
earning rows of 9.01 each, and a loopback-only STARTTLS capture server.
These ledger fixtures are not factory price approval or real earned amounts.
SMTP captures stay in process memory; no real recipient or SMTP service is used.
No factory invitation/confirmation workflow is invoked.

Only the owned restored database is processed. The original synthetic database
is re-fingerprinted at the end and must remain unchanged. Every business table
is compared, excluding only outbox delivery state and the journal's explicit
email-status/error/timestamp fields. Message IDs, tenant IDs, journal references
and payloads must remain identical; no new jobs may appear.

The opt-in runner requires 1,024 MiB available RAM before touching Docker.
The resume phase runs at most three capped containers (PostgreSQL 128 MiB,
MinIO 192 MiB, probe 256 MiB). This test is run on GitHub Actions instead of
stopping normal services on the 4 GiB development PC. Temporary PDFs, source
snapshots, database/object-store volumes and certificates are cleaned up.
CI retains only the synthetic execution log for seven days.

## Scenarios

1. Restore the complete migrated schema and exact PDF objects.
2. Five original queue jobs: two due PENDING (including one previously retried),
   one SENT, one exhausted FAILED and one future PENDING.
3. Connection refusal preserves both due jobs, increments failure attempts,
   applies backoff, and does not change business rows. Immediate retry is idle.
4. A new process reads the persisted retry state. Advancing only the synthetic
   deadlines allows both restored PDFs to be submitted once over real STARTTLS.
   SENT, FAILED and future jobs remain untouched; another pass is idle.
5. Dump after successful SENT commits, restore into another fresh database:
   the worker does not send anything again.
6. Restore the original pre-send dump into another fresh database: previously
   accepted mail is submitted again. This intentionally reproduces a stale
   backup risk, not a successful exactly-once guarantee.
7. Inject a failed DB commit after SMTP acceptance: one email is accepted twice
   when the retained job retries, but work, earnings and signatures do not repeat.

## Execution

```sh
python -B -m unittest discover -s tests -p 'test_*restore_safety.py' -v
python -B scripts/test_full_restore_acceptance.py --resume-outbox \
  --postgres-image sha256:<cached-image-id> \
  --app-image sha256:<cached-image-id> \
  --storage-image sha256:<cached-image-id>
```

Workflow: `Restored Outbox Acceptance`.
2026-10-24: 32 host safety tests passed; remote runtime pending.

## Safe operational sequence

This is a runbook, not authorization to alter a working deployment:

1. Keep outbound workers stopped before and throughout recovery. Ensure the
   service manager will not auto-start them. Do not rely on EMAIL_ENABLED alone:
   the current outbox loop processes queued EMAIL jobs independently of that flag.
   Do not start two workers against the same queue; the current worker commits
   per message and releases the rest of its batch locks.
2. Restore DB and PDFs into an isolated target. Check snapshot cut-off time,
   schema/data fingerprints, object integrity and journal references first.
3. Preserve the restored outbox as evidence. Never truncate/recreate it, reset
   all attempts or re-run signing, completion, factory confirmation or accrual.
4. SENT jobs remain SENT. Future jobs retain their schedule. Exhausted FAILED
   jobs require the existing authorized retry flow after diagnosis; SMTP being
   available is not permission to resurrect them automatically.
5. For PENDING jobs, reconcile any interval between the backup cut-off and the
   failure against independent SMTP/provider records. An accepted message may
   look PENDING in a stale backup or after an uncertain DB commit. SMTP acceptance
   itself is not proof of delivery to the recipient's inbox.
6. If evidence is incomplete, keep outbound processing stopped. Do not silently
   mark uncertain messages SENT (which could lose mail), or blindly retry them
   (which could duplicate it). An authorized, recorded decision is required.
   There is no new production reconciliation UI or per-job recovery hold in
   this change; do not resolve this by unaudited SQL edits.
7. Only after the boundary is verified/reconciled, resume one worker and monitor
   failures/backoff. Recheck work/earning/signature counts and sums. Re-delivery
   is a communication action, never a reason to repeat business actions.

## Remaining operational gap

Automatic unattended resumption from an arbitrary old backup is NOT approved.
Plain SMTP and a database commit do not form one atomic transaction. A durable,
audited recovery hold/reconciliation workflow and independent provider evidence
are needed for that use case; a stable Message-ID alone is not deduplication.
Multi-worker races, large-volume recovery, external provider delivery receipts,
factory invitation validity after recovery, and a real business database are
outside this synthetic journal-email acceptance.
