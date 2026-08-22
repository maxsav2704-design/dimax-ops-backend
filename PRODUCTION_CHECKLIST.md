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
