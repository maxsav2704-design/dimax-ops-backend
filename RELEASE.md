# Release Runbook

Before each release, fill the workspace-level template in `../RELEASE_TEMPLATE.md`
and use `../POST_DEPLOY_SMOKE.md` as the default smoke checklist record.

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

From workspace root you can run the same gate through the isolated test runtime:

```powershell
.\workspace.cmd test-backend-gate
.\workspace.cmd test-frontend-gate
.\workspace.cmd test-mobile-gate
.\workspace.cmd test-production-image
.\workspace.cmd test-release-gate
```

This avoids the dev workspace API process with `--reload` and gives explicit gates for:

- backend integration/runtime
- fresh and legacy-schema Alembic upgrade/downgrade safety, including preservation
  of the pre-`0049` product library and client price-list references
- exact Python dependency resolution plus `pip check`
- immutable production image, non-root runtime, secret/test exclusion and OCR runtime
- admin frontend (`vitest + next build`)
- mobile installer app (`vitest + expo config + tsc`)

## 2. Deployment Order

1. Pull release commit/tag to target environment.
2. Create `.env.production.local` with owner-provisioned values and validate it:

```bash
python scripts/validate_production_env.py --env-file .env.production.local
```

Production Compose sets `APP_ENV=production`. The image entrypoint repeats the
runtime subset of this validation for migrations, workers, and the API, so a
missing or unsafe operational secret cannot fall back to development defaults.

`DIMAX_BACKEND_IMAGE` must identify the exact release with either a sha256 digest
or a tag ending in the 12-64 character source SHA. `latest`, missing values, and
ordinary floating tags are rejected.

3. Ensure the external PostgreSQL and S3/MinIO services are reachable and take a database backup/snapshot.
4. Validate the production topology and build the immutable backend image:

```bash
export DIMAX_BACKEND_ENV_FILE=.env.production.local
docker compose -f docker-compose.production.yml --env-file .env.production.local config --quiet
docker compose -f docker-compose.production.yml --env-file .env.production.local build api
```

`constraints.txt` pins the complete tested Python dependency graph. The image
build must fail on a dependency conflict, and the workspace production-image
gate verifies UID/GID `10001`, absence of `.env` and test sources, application
import, `pip check`, and the required English/Hebrew/Russian OCR languages.

5. Apply migrations as a separate one-shot operation. Do not start application services if it fails:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production.local run --rm migrate
```

6. On the first deployment of an empty database only, create the initial company,
   OWNER admin, default plan, door types, and operational reasons:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production.local run --rm bootstrap
```

The bootstrap is idempotent and never prints or resets an existing admin password.
Record the company UUID printed by the command, sign in, and rotate the temporary
password. Do not make bootstrap part of routine deployments because it also
reconciles the initial catalog names.

7. Start the API and all operational workers:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production.local up -d \
  api sync-health outbox-worker maintenance-worker sync-gc-worker
```

`docker-compose.production.yml` intentionally contains no local PostgreSQL or MinIO,
no source-code mount, and no Uvicorn `--reload`. By default the API binds to
`127.0.0.1:8000` for a host reverse proxy. Override `DIMAX_API_BIND` only when the
target network topology requires it. Seed credentials are masked in API and worker
containers and are exposed only to the one-shot bootstrap service.

## 3. Post-Deploy Smoke

```bash
docker compose -f docker-compose.production.yml exec -T api curl -fsS http://localhost:8000/health
docker compose -f docker-compose.production.yml exec -T api curl -fsS http://localhost:8000/ready
curl -fsS https://<api-host>/health
curl -fsS https://<api-host>/ready
curl -fsS https://<api-host>/openapi.json > /dev/null
```

Integration tests run in the pre-release gate, not inside the production container.

Manual API checks:

- Admin login (`/api/v1/auth/login`)
- Admin dashboard (`/api/v1/admin/dashboard`)
- Public file/journal route (if token exists)
- Installer login + workspace/projects/schedule path
- Record outcome in `../POST_DEPLOY_SMOKE.md`

Mobile checks before calling release complete:

- `.\workspace.cmd preflight-mobile-device`
- `.\workspace.cmd smoke-mobile`
- manual installer login on emulator/device
- manual open of assigned projects list
- manual open of one project with doors/issues/add-ons

## 4. Rollback

If deploy fails after migration:

1. Stop API:
   - `docker compose -f docker-compose.production.yml stop api sync-health outbox-worker maintenance-worker sync-gc-worker`
2. Return app image/commit to previous stable version.
3. Run DB rollback only if migration is verified reversible:
   - `docker compose -f docker-compose.production.yml run --rm migrate alembic downgrade -1`
4. Start previous API version.
5. Re-run health + smoke checks.

If rollback safety is unclear, keep DB at current schema and roll forward with hotfix.

If the incident is operational rather than deployment-related, use `INCIDENT_RUNBOOKS.md` instead of improvising direct DB fixes.

## 5. Release Done Criteria

- `quality-gate` is green in CI.
- Production image contract is green for the exact release source.
- Production `/health` is OK.
- OpenAPI contract smoke passes.
- No error spike in first monitoring window.
- Mobile gate is green and manual installer smoke is completed on a real device/emulator.
