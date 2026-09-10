# Testing

## Prerequisites

- Docker Desktop is running.
- Workdir: `backend`.

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

```bash
docker compose run --rm --no-deps api pytest -q tests/integration/test_auth_guards_api.py tests/integration/test_admin_access_and_validation.py tests/integration/test_installers_link_user_api.py tests/integration/test_installer_rates_api.py
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
