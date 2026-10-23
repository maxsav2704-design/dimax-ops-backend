# Outbox health acceptance: 2026-10-23

## Scope and defect

After the previous commit-boundary correction, `run_once()` correctly stopped
its batch and returned only the committed count on database failure. However,
`main()` still refreshed the heartbeat unconditionally after that return. A
worker unable to persist outcomes could therefore keep reporting healthy.

A new regression test reproduced this with the actual worker loop and synthetic
session/repository/sender doubles: after a failed commit, `healthy()` returned
True. The baseline run failed that assertion before the production-code change.

## Correction

- Publish a heartbeat only at the successfully committed end of `run_once()`.
- Remove the prior marker on a message commit failure; the outer loop must not
  overwrite that failure with a healthy marker.
- Invalidate the marker if session creation, fetching, final commit or another
  unhandled worker-loop error fails. Existing process failure behavior remains.
- Retain `run_once()`'s integer result and existing SMTP retry/business behavior.
- A handled SMTP outage with a durably saved retry is a healthy worker pass, not
  successful delivery. Do not restart a correctly working queue just because
  its remote SMTP provider is unavailable.
- Keep heartbeat writes outside per-message delivery exception handling. A
  heartbeat-file error must not reclassify an already committed SENT job as FAILED.

The marker still contains only PID and monotonic completion time, no addresses,
tokens, subjects or document data. The single-worker assumption is unchanged.
No migration, API response change, price, signature or earnings change is needed.

## Local evidence

The isolated, cached Python image ran with networking disabled, a read-only
filesystem/source mounts, no database/storage/socket mounts and temporary files
only in tmpfs. The production entrypoint was bypassed. Sessions and message
sending are mocked in the worker health tests; the existing SMTP transport tests
use real STARTTLS on container loopback only.

**43 tests passed in 7.35 seconds**: 25 health cases, four commit-boundary cases,
ten SMTP unit cases and four SMTP TLS transport cases. Coverage includes:

- empty and successfully sent batches;
- first/second message commit failure and failure recording an SMTP outage;
- query, session creation and final-commit failures;
- invalidation of an existing fresh marker, followed by recovery on a saved pass;
- SMTP outage with a saved retry and heartbeat-file write failure;
- stale/malformed/future/dead-process marker checks and existing TLS checks.

Workspace production configuration regression also passed: 19 Python tests
passed, six Linux deployment-shell cases were skipped on Windows, and all four
Node infrastructure contract cases passed. The updated PowerShell runner parsed
without syntax errors. Both temporary health-test containers were absent after
the runs; no application services needed restarting or cleanup.

This is not a repeated real-PostgreSQL acceptance run or the whole backend suite.
The earlier real-database evidence remains in `OUTBOX_SMTP_ACCEPTANCE.md`.
The full runner now includes the health module for its next invocation on a host
with sufficient memory; it was not rerun here. Working services were not stopped,
restarted or redeployed, and no working database was connected by these tests.

To repeat the lightweight check from the backend directory, use a cached reviewed
image (the ID below was used for this run), not a production container:

```powershell
$backend = (Resolve-Path -LiteralPath '.').Path
$image = 'sha256:f5af3ba59394a1d77dd98f74b7a57c96018d96be616e8534fcdbeaa67e335b74'
$mounts = @('--mount', "type=bind,source=$backend\app,target=/app/app,readonly")
$tests = @('architecture/test_outbox_health.py', 'test_outbox_commit_boundary.py',
           'test_smtp_sender.py', 'test_smtp_tls_transport.py')
foreach ($test in $tests) {
    $source = Join-Path "$backend\tests" $test
    $name = Split-Path $test -Leaf
    $mounts += @('--mount', "type=bind,source=$source,target=/tests/$name,readonly")
}
docker run --rm --pull never --network none --read-only --memory 256m `
  --pids-limit 128 --cap-drop ALL --security-opt no-new-privileges:true `
  --tmpfs /tmp:rw,noexec,nosuid,size=32m --workdir /tmp `
  --env PYTHONPATH=/app --env APP_ENV=test @mounts `
  --entrypoint python $image -B -m pytest --noconftest `
  -p no:cacheprovider -q --tb=short /tests
```

## Operational interpretation

1. Use the existing production probe `python -m app.workers.outbox_health` inside
   the outbox worker container. Do not run it in the API container or on the host.
2. A missing/invalid/stale marker or dead PID means the committed worker pass
   cannot be confirmed. Inspect worker logs and database/storage availability.
3. After a successful saved pass, the marker becomes healthy again. A long or
   hung batch still uses the existing 600-second maximum age; Docker applies its
   configured interval/retry/start-period thresholds before changing health state.
4. Check the existing authorized `/api/v1/admin/outbox/summary` separately:
   `failed_total` and `pending_overdue_15m` expose delivery backlog. Inspect the
   individual errors and use audited retry controls only after fixing the cause.
   Do not replay installation, signing, price activation or earnings to resend mail.
5. Docker health state alone is not an alerting service and does not automatically
   restart an unhealthy-but-running container. The existing restart policy covers
   process exits. External monitoring/notifications still need infrastructure.

Actual external delivery, alert routing, multi-worker concurrency and public
HTTPS remain separate acceptance tasks. Possible duplicate email at the
SMTP-accepted/database-commit boundary is not removed by this health correction.
