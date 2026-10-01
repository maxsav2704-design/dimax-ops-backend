# Testing

## Prerequisites

- Docker Desktop is running.
- Workdir: `backend`.

## Journal Signature and PDF Integrity

Manual-send `outbox_ids` must contain the UUIDs of the persisted queue rows,
matching `JOURNAL_SEND_REQUESTED` audit data. Unselected channels return JSON
null. Each intentional resend creates distinct IDs. Delivery API tests cover
email, WhatsApp and both channels, plus rollback of queue rows, file-token/file
records, delivery statuses and send audits on preparation or audit failure.
These rollback checks cover the database transaction, not external object-store
writes. UUIDs are allocated before enqueue without an extra flush or commit.

On an isolated migrated test database (set both `DATABASE_URL` and
`TEST_DATABASE_URL`), run:

```bash
pytest -q tests/architecture/test_transaction_boundary.py tests/integration/test_journal_delivery_api.py
```

Human signing links use `PUBLIC_APP_BASE_URL/acceptance/{token}`, never the JSON
API origin. Manual email/WhatsApp messages, fallback email, template previews and
admin/installer snapshots share the same eligibility check: ACTIVE, unsigned,
token present, expiry strictly in the future (legacy null expiry is supported).
Draft, signed or expired documents can still be sent as PDFs without a dead
signing link. API file/media URLs and mark-ready's legacy `public_url` field are
unchanged; its separate `signing_url` remains the human URL. No existing queued
messages are rewritten and no token expiry is automatically extended.

```bash
pytest -q tests/architecture/test_journal_signing_links.py tests/architecture/test_journal_snapshot_contract.py tests/integration/test_journal_delivery_api.py tests/integration/test_catalogs_and_settings_api.py tests/integration/test_journal_api.py
```

New signatures use the existing canvas format: a positive numeric `viewport`
and bounded, finite point `strokes` containing a visible line. Blank, malformed,
degenerate and excessive payloads return 422 before changing the journal.
The signing transaction finalizes a separate `_signed.pdf` object once. Exports,
downloads and resends reuse the signed archive, including legacy object paths;
they must never reconstruct it from today's project metadata. Missing archives
must be restored, not silently regenerated. No schema migration is required.

On an isolated migrated test database, run:

```bash
pytest -q tests/architecture/test_journal_pdf_integrity.py tests/architecture/test_journal_pdf_freshness.py tests/architecture/test_journal_snapshot_contract.py tests/architecture/test_journal_filter_contract.py tests/integration/test_journal_api.py tests/integration/test_journal_delivery_api.py tests/integration/test_e2e_core_flow.py
```

`tests/integration/test_journal_mailpit_acceptance.py` is opt-in via
`DIMAX_JOURNAL_MAILPIT=1`. It requires `APP_ENV=test`, both database URLs pointing
to `db/dimax_acceptance_tests`, SMTP `mailpit:1025` with TLS/auth disabled,
MinIO `minio:9000` bucket `acceptance`, email enabled and WhatsApp disabled.
Its module-scoped guard executes before database fixture inserts. The real
storage/SMTP test runs the outbox worker only for its own ephemeral company,
verifies the returned invitation ID resolves to the sent queue row and checks
its human URL, compares the received PDF bytes and
signed delivery To/Cc recipients, then removes only its own
Mailpit messages and MinIO prefix. Database fixtures clean their own company.
It does not send externally or process the acceptance application's queue.

Optionally mount an ignored QA directory at `/qa` and set
`DIMAX_JOURNAL_QA_DIR=/qa` to retain two small PDFs for visual inspection. Render
all their pages with Poppler, inspect them, then remove these temporary artifacts.
Mailpit receipt is not proof of external inbox delivery or legal signature validity.

## Installer Earnings Date Contract

Installer earnings use `Asia/Jerusalem` calendar dates, matching the installer
workspace. Day/week/month ranges are half-open: local start inclusive, next local
period start exclusive. Weeks still start on Monday. The optional `date` remains
a calendar date, not a UTC timestamp. Without it, one local date is captured for
all totals in the response.

`completed_at` remains a timezone-aware stored instant. No ledger values, rate
snapshots, correction rules, schema or API fields change. Existing offline
snapshots remain historical cached responses until a successful online refresh.

On an isolated migrated test database, run:

```bash
pytest -q tests/integration/test_installer_phase2_api.py tests/integration/test_earnings_corrections_api.py tests/integration/test_financial_integrity_constraints.py tests/integration/test_calendar_api.py
```

Regressions cover local midnight, week/month/year boundaries, implicit current
date, workspace reconciliation, DST short/long days, exclusive range ends and
preservation of stored work timestamps and amounts. This API evidence does not
replace native-device or live UI acceptance.

## Door Assignment and Completion Atomicity

Assignment, completion, admin override and sync status writes lock the tenant's
door row before validating mutable state. Write reads refresh cached ORM values
after acquiring the lock. Legacy installer actions recheck the expected installer
inside the write transaction, even if the earlier request guard already passed.
Bulk assignments lock IDs in stable order while retaining response order.
No schema migration, public request field or completion/pricing rule is changed.

```bash
pytest -q tests/integration/test_door_assignment_atomicity.py
```

Regressions cover interleaved transactions with stale reads, both assignment APIs,
legacy guard timing, PostgreSQL NOWAIT exclusion/release, simultaneous completion
with one accrual/history entry, and real JWT visibility/payroll reconciliation for
an owner and two installers. Guard timing is simulated explicitly in two tests;
it is not described as an unmodified-browser race demonstration.

## Installer Sync Replay Contract

For `/api/v1/installer/sync`, an existing `client_event_id` acknowledges only
the original installer, project, event type, payload and client timestamp. A
different event with that key receives the existing
`CONFLICT_INVALID_TRANSITION` acknowledgement; another installer still receives
`CONFLICT_ASSIGNMENT_CHANGED`. The original stored event is never overwritten.
Exact retries after response loss remain `ok=true, applied=false`, including
JSON key reordering, equivalent timestamp offsets and omitted timestamps when
both the original and retry omit them. Legacy naive timestamps are treated as
UTC for replay comparison. No schema or response field changes are required.

```bash
pytest -q tests/integration/test_sync_installer_snapshot_api.py tests/integration/test_sync_batch_api.py tests/integration/test_door_assignment_atomicity.py tests/integration/test_financial_integrity_constraints.py tests/integration/test_openapi_contract.py
```

The new replay cases use real JWT login, the API transaction boundary and an
isolated PostgreSQL database. They check one installation, one status-history
entry, one change-log entry and one 250.00 accrual after repeated delivery.
Collision cases cover both the initial lookup and a simulated missed lookup
followed by a real unique-constraint violation. This is not a physical network
interruption or proof of native SQLite durability. Mobile service tests verify
preserved event identity on network/503/missing-ACK retries and payload retention
after a rejected acknowledgement.

## Import Numeric Contract

Imported door quantities must be finite whole numbers from 1 to 1000. Decimal
and comma notation for whole numbers remain accepted; fractional quantities must
never be silently truncated. Prices must be finite nonnegative decimals. Blank
values retain the existing quantity/default-price behavior.

```bash
pytest -q tests/integration/test_file_import_numeric_validation.py tests/integration/test_project_file_import_api.py
```

Tests cover numeric boundaries, preview without door writes, atomic refusal of
invalid files, explicit partial import and revalidation of pre-fix cached previews.
The fingerprint version changes; existing door identity still prevents repeat
inserts and import history is retained. No stored quantities are automatically
repaired: historical files with fractional quantities need reconciliation against
their source. No database migration or public API field changes are required.

## Workspace Test Runtime

From workspace root you can use the isolated test compose without `uvicorn --reload`:

```powershell
.\workspace.cmd smoke-test-backend
.\workspace.cmd test-backend
.\workspace.cmd test-backend-gate
.\workspace.cmd test-frontend-gate
```

This path uses `docker-compose.workspace.test.yml` and is safer than the dev workspace stack for integration verification.
It expects the local workspace backend image `dimaxoperationssuite-api` to exist. If it is missing, build/start the dev workspace API once.
The workspace wrapper disables pytest plugin autoload for deterministic container runs.

## Local Run (Fast)

```bash
docker compose up -d db minio api
docker compose exec api alembic upgrade head
docker compose exec api pytest -q tests/integration
```

## Dev seed for local/e2e

Idempotent dev seed:

```bash
docker compose exec -T -e APP_ENV=dev api python -m app.scripts.seed_dev
```

Machine-readable output for workspace/e2e bootstrap:

```bash
docker compose exec -T -e APP_ENV=dev api python -m app.scripts.seed_dev --emit-json
```

This seed guarantees:

- dev company exists
- admin + installer users exist
- installer records exist for installer users
- `installer_sync_state` exists for seeded installers

## Local Run (CI Equivalent)

```bash
docker compose up -d db minio
python scripts/verify_repo_boundary.py
docker compose run --rm --no-deps api alembic upgrade head
python scripts/db_backup_restore_smoke.py
docker compose run --rm --no-deps api pytest -q tests/architecture/test_module_structure.py
docker compose run --rm --no-deps api pytest -q tests/integration/test_openapi_contract.py
docker compose run --rm --no-deps api pytest -q tests/integration/test_auth_guards_api.py tests/integration/test_admin_access_and_validation.py tests/integration/test_installers_link_user_api.py tests/integration/test_installer_rates_api.py
docker compose run --rm api pytest -q tests/integration
docker compose down -v
```

This sequence corresponds to upstream jobs aggregated by CI `quality-gate`.

To verify branch protection is actually active in GitHub:

```bash
python scripts/verify_branch_protection.py --repo "<owner>/<repo>" --branch "main"
```

## OpenAPI Contract Only

```bash
docker compose run --rm --no-deps api pytest -q tests/integration/test_openapi_contract.py
```

## Architecture Contract Only

```bash
docker compose run --rm --no-deps api pytest -q tests/architecture/test_module_structure.py
```

## Repo Boundary Only

```bash
python scripts/verify_repo_boundary.py
```

## Backup/Restore Smoke Only

```bash
docker compose up -d db
docker compose run --rm --no-deps api alembic upgrade head
python scripts/db_backup_restore_smoke.py
docker compose down -v
```

## Error Contract Only

Expired access and refresh JWTs return 401 / UNAUTHORIZED, allowing clients to
refresh a valid session or end an expired one. Invalid signatures, wrong token
types and permission denials retain their existing 403 contract. Token lifetimes,
refresh rotation/replay protection and tenant/role checks are unchanged.
`test_expired_session_api.py` covers admin/installer recovery, expired refresh,
and multipart upload retry without duplicate doors using real authentication.

```bash
docker compose run --rm --no-deps api pytest -q tests/integration/test_auth_guards_api.py tests/integration/test_expired_session_api.py tests/integration/test_admin_access_and_validation.py tests/integration/test_installers_link_user_api.py tests/integration/test_installer_rates_api.py
```

## Migration Smoke (Manual)

```bash
docker compose up -d db
docker compose run --rm --no-deps api alembic upgrade head
docker compose run --rm --no-deps api alembic downgrade base
docker compose run --rm --no-deps api alembic upgrade head
docker compose down -v
```

## When Dependencies Change

If `requirements.txt` changed, rebuild `api` image before running `docker compose run`:

```bash
docker compose build api
```

## Integration Coverage Matrix

### Journal document languages and pagination

`tests/architecture/test_journal_pdf_layout.py` checks RU/EN/HE labels,
35 unique door positions, multi-page comments, notes and the signature block.
It verifies bidi conversion after line wrapping, including explicit newlines.
Mixed-direction PDF text is also inspected with a pypdf visitor because default
text extraction can omit Latin runs next to Hebrew. Rendered-page inspection
remains necessary; successful extraction alone does not establish visual quality.

`tests/integration/test_journal_delivery_api.py` checks persisted language,
auditing, header locks, DRAFT-only editing, invalid API/DB values and unchanged
signed PDF bytes. Installer preparation retains an existing draft's language.
New clients send `pdf_locale`; omitted values remain backward compatible (`en`).

Migration `0061_journal_pdf_locale` adds a checked, non-null field with an English
default and does not regenerate files. `scripts/db_journal_locale_migration_smoke.py`
requires APP_ENV=test, DIMAX_JOURNAL_LOCALE_MIGRATION=1 and an empty database named
`dimax_journal_locale_migrations` on host `db`. It verifies the full migration
chain, a preexisting archive reference, the default/check constraint and one-step
rollback/re-upgrade. Never run the destructive rollback check against live data.

September 21 focused regression: 88 PASS including existing signature integrity,
freshness, snapshot, transaction, access and opt-in local Mailpit delivery tests.
This does not replace the full release gate or external delivery acceptance.

### Issue lifecycle and incremental sync

`tests/integration/test_issue_lifecycle_sync.py` covers reporting, individual and
bulk closure, the preceding uncompleted door state, installed-door payroll
preservation, contradictory statuses, installer reassignment and issue delivery.
It also checks that a comment refreshes an issue closed after its initial read,
so an old in-memory status cannot be published back to the phone.
Closing an issue is not an installation. Opening a defect on an installed door
does not reverse completed work. Closed issues remain in assigned cold snapshots.

The mobile handler removes only the acknowledged optimistic issue. When a server
issue arrives, it also removes orphaned local copies left by older clients for
that door, but preserves every local copy still backed by a pending event.

Migration `0062_issue_sync` adds the `ISSUE` change type and backfills existing
assigned issues without changing business rows. Apply the migration before
restarting backend processes. Deploy the updated mobile sync handler with it;
older clients ignore this event type and do not provide correct incremental
issue updates. A client that already consumed events with an old handler needs
a supported cold resync after reconciling its pending work, never a data clear.

`scripts/db_issue_sync_migration_smoke.py` requires APP_ENV=test,
DIMAX_ISSUE_SYNC_MIGRATION=1 and an empty disposable database named
`dimax_issue_sync_migrations` on host `db`. It tests the full migration chain,
OPEN/CLOSED issue backfill, rollback and repeat upgrade without payroll changes.
Rollback removes only the derived ISSUE change-log rows and retains business
issues and the additive PostgreSQL enum label. Do not run this smoke on live data.

### Add-on quantity, payroll and replay

`tests/integration/test_addons_api.py` covers shared offline/direct quantity
validation, nonfinite values, Numeric(12,2) boundaries, unrepresentable payroll
amounts, half-up cent rounding, immutable earned-rate snapshots, altered replay
payloads and simultaneous writes. Run it with `test_sync_batch_api.py` and
`test_payroll_lifecycle.py` for both sync paths and existing correction behavior.

Quantity validation now runs in the add-on use case, not only the HTTP schema.
A finite positive quantity has at most 10 integer and 2 decimal digits. For a
positive installer rate, the rounded earned amount must fit 0.01..9999999999.99;
invalid requests roll back the fact as well as its earnings. Zero/missing prices
still allow the existing late-plan reconciliation flow. Updating a plan does
not rewrite an already accrued snapshot.

Identical direct retries retain `ok=true, applied=false`. Reusing the key for
different work now returns HTTP 409 (or a sync conflict), rather than a false
successful acknowledgment. Blank/oversized event IDs are validation errors.
Plan writes and fact creation lock the same project row within the existing
unit of work, and the existing unique fact/ledger constraints remain in place.
No schema change or migration is needed for this hardening.

The installer earnings type summary accumulates quantities as Decimal, including
sub-unit work and multiple fractional facts. Its JSON quantity remains a number,
now preserving the fraction instead of truncating each fact to an integer.
`jobs_count` still counts ledger rows; earned amounts and rate snapshots do not
change. Mobile accepts both numeric and decimal-string quantities.

### Module coverage

- `auth`: `tests/integration/test_auth_api.py`, `tests/integration/test_auth_guards_api.py`
- `installers`: `tests/integration/test_installers_api.py`, `tests/integration/test_installers_link_user_api.py`
- `installer_rates`: `tests/integration/test_installer_rates_api.py`
- `admin access + validation`: `tests/integration/test_admin_access_and_validation.py`
- `projects`: `tests/integration/test_projects_admin_api.py`
- `reports`: `tests/integration/test_reports_api.py`
- `dashboard`: `tests/integration/test_dashboard_api.py`
- `openapi contract`: `tests/integration/test_openapi_contract.py`
- `list contracts`: `tests/integration/test_admin_list_contracts.py`
- `multi-tenant isolation`: `tests/integration/test_multi_tenant_isolation.py`
