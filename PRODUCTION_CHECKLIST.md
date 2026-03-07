# Production Checklist

## Secrets And Env

- `JWT_SECRET` is strong and not `change-me`.
- `DATABASE_URL` points to production database, not local docker defaults.
- `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` are rotated production credentials.
- `SEED_ADMIN_PASSWORD` is changed from default.
- `PUBLIC_BASE_URL` is production HTTPS URL.
- `CORS_ALLOW_ORIGINS` does not contain localhost values.
- `MINIO_SECURE=true` in production.
- If `EMAIL_ENABLED=true`, SMTP points to a real provider and `SMTP_FROM` is not `.local`.
- If `WHATSAPP_ENABLED=true`, Twilio credentials are present or `WHATSAPP_FALLBACK_TO_EMAIL=true`.

Validate before deploy:

```bash
python scripts/validate_production_env.py --env-file .env
```

## Safety Gates

- `Backend Tests / quality-gate` is required on protected branch.
- `Backend Tests / repo-boundary` is green.
- `Backend Tests / backup-restore-smoke` is green.

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
```

Manual checks:

- admin login
- installer login
- one file/journal public route
- one report endpoint
