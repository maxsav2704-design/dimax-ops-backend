# Release Runbook

## 1. Pre-Release Gate

From `backend`:

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

## 2. Deployment Order

1. Pull release commit/tag to target environment.
2. Ensure production secrets/env are set (see `PRODUCTION_CHECKLIST.md`).
3. Build and start dependencies:

```bash
docker compose up -d db minio
docker compose build api
```

4. Apply migrations:

```bash
docker compose run --rm --no-deps api alembic upgrade head
```

5. Start API/services:

```bash
docker compose up -d api sync-health
```

## 3. Post-Deploy Smoke

```bash
docker compose exec api curl -fsS http://localhost:8000/health
docker compose exec api pytest -q tests/integration/test_openapi_contract.py
```

Manual API checks:

- Admin login (`/api/v1/auth/login`)
- Admin dashboard (`/api/v1/admin/dashboard`)
- Public file/journal route (if token exists)

## 4. Rollback

If deploy fails after migration:

1. Stop API:
   - `docker compose stop api sync-health`
2. Return app image/commit to previous stable version.
3. Run DB rollback only if migration is verified reversible:
   - `docker compose run --rm --no-deps api alembic downgrade -1`
4. Start previous API version.
5. Re-run health + smoke checks.

If rollback safety is unclear, keep DB at current schema and roll forward with hotfix.

## 5. Release Done Criteria

- `quality-gate` is green in CI.
- Production `/health` is OK.
- OpenAPI contract smoke passes.
- No error spike in first monitoring window.
