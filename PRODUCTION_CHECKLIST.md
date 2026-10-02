# Production Checklist

## Secrets And Env

- `DIMAX_BACKEND_IMAGE` uses a sha256 digest or a release tag ending in a
  12-64 character source SHA; `latest` and ordinary floating tags are rejected.
- `JWT_SECRET` is random, at least 32 characters, and not a placeholder.
- `DATABASE_URL` points to PostgreSQL outside the dev compose and enforces TLS with `sslmode=require`, `verify-ca`, or `verify-full`.
- `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` are rotated production credentials.
- `SEED_ADMIN_EMAIL` is the real owner/admin email.
- `SEED_ADMIN_PASSWORD` is at least 14 characters and must be rotated after first login.
- `PUBLIC_BASE_URL` is production HTTPS URL.
- `CORS_ALLOW_ORIGINS` does not contain localhost values.
- `MINIO_SECURE=true` in production.
- `EMAIL_ENABLED`, `WHATSAPP_ENABLED`, `WHATSAPP_FALLBACK_TO_EMAIL`, and `TWILIO_WEBHOOK_VALIDATE` are set explicitly.
- `EMAIL_ENABLED=true`; SMTP points to a real provider, TLS is enabled, and `SMTP_FROM` is a real address. Signed journal PDF delivery is a required production workflow.
- If `WHATSAPP_ENABLED=true`, configure the complete Twilio set and signature validation, or explicitly enable email fallback with working SMTP.
- Empty `OUTBOX_WEBHOOK_TOKEN` disables the generic provider webhook. Enabling it requires a random token of at least 32 characters.

Validate before deploy:

```bash
python scripts/validate_production_env.py --env-file .env.production.local
```

The production image also runs the runtime subset of this validation from its
entrypoint whenever `APP_ENV=production`. Missing or unsafe operational values
therefore stop migrations, workers, and the API before application startup.

Starter example:

- `.env.production.example`

The example contains placeholders and must fail validation until the owner replaces them.

For a new empty database, run migrations and then the one-shot bootstrap before
starting the API:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production.local run --rm migrate
docker compose -f docker-compose.production.yml --env-file .env.production.local run --rm bootstrap
```

Bootstrap creates the initial company, OWNER profile, default plan, door types, and
reasons. It is idempotent, does not reset an existing password, and does not print
the password. Rotate the temporary password after first login.

Validate the production container topology without starting it:

```bash
DIMAX_BACKEND_ENV_FILE=.env.production.example \
DIMAX_BACKEND_IMAGE=dimax-backend:contract-000000000000 \
docker compose -f docker-compose.production.yml config --quiet
```

Build and verify the exact release image from the workspace root:

```powershell
.\workspace.cmd test-production-image
```

Expected contract:

- dependency graph is resolved through exact `constraints.txt` pins and `pip check` passes;
- image defaults to UID/GID `10001` with all Linux capabilities dropped at runtime;
- backend `.env` files and test sources are absent from the image;
- FastAPI imports successfully and Tesseract provides `eng`, `heb`, `osd`, and `rus`.

## Safety Gates

- `Backend Tests / quality-gate` is required on protected branch.
- `Backend Tests / repo-boundary` is green.
- `Backend Tests / backup-restore-smoke` is green.
- the legacy `product_library` upgrade/downgrade smoke is green and preserves
  product rows, price-list foreign keys, and canonical index names.
- production image contract is green for the release commit.
- Uvicorn access logging stays disabled, and the reverse proxy logs public
  file/journal routes as templates without capability tokens or query values.

## Factory Price Authority (Open)

The October 2 business requirement is not yet a release PASS. Migration 0063 and
`/api/v1/admin/price-lists` add company-wide immutable versions. Migration 0064
adds expiring/revocable invitations and explicit, version-bound factory decisions
(CONFIRMED). The public `/price-approval` page supports RU/EN/HE without access
to projects, installers or payroll. Existing installer/project rates still serve
the legacy payroll paths; do not describe them as factory-confirmed. Confirmation
currently records the decision; it does not activate prices or change earnings.
The admin `/price-lists` workspace now supports draft creation/copy/cancellation,
named invitations, one-time manual link sharing, revocation and decision history
in RU/EN/HE. OWNER/OPERATIONS can write with rate access; FINANCE can read with
rate access. There is no admin substitute for the factory's explicit decision.

Before production approval under the new rule:

- reconcile existing per-installer/per-project prices without inventing approval;
- configure controlled delivery and HTTPS; verify the factory contact before
  sharing the link, which is a bearer capability,
  not independent proof of the holder's identity;
- activate only confirmed prices, retaining the previous confirmed version while
  an amendment is pending and preserving historical completed-work snapshots;
- connect active-price state in the admin UI and read-only mobile offline cache;
- verify confirmation, concurrent amendments, offline work and earnings end to end.

Neither migration backfills or approves existing rates. Both downgrades refuse
to discard recorded history. The guarded migration scripts
`scripts/db_factory_price_list_migration_smoke.py` and
`scripts/db_factory_price_approval_migration_smoke.py` exercise a fresh database,
upgrade/rollback/re-upgrade, preserved legacy payroll and metadata agreement.
The confirmation lifecycle has database-backed concurrency/retry/rollback tests;
public-page and admin-management browser tests use mocked responses, not real
factory decisions. The UI-only management step adds no migration or backend
runtime change and does not replace backend/mobile release gates.
No email/WhatsApp delivery or native-device acceptance is claimed by this step.
Public request throttling currently uses the existing process-local limiter;
production multi-worker deployments still need shared/gateway-level limits.

## Backup/Restore Drill

Run before first production deploy and on schedule:

```bash
docker compose up -d db
docker compose run --rm --no-deps api alembic upgrade head
python scripts/db_backup_restore_smoke.py
docker compose down -v
```

Expected result:

- `[backup-restore] OK: restored tables=<N>`

## Deploy Smoke

After deploy:

```bash
curl -fsS https://<api-host>/health
curl -fsS https://<api-host>/ready
```

Manual checks:

- admin login
- installer login
- one file/journal public route
- one report endpoint
