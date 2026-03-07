# DIMAX Operations Suite Backend

FastAPI backend for the DIMAX Operations Suite.

## Scope

This repository owns:

- authentication and role guards
- multi-tenant company isolation
- installers and installer rates
- projects, doors, issues and add-ons
- dashboard, reports and journal flows
- files/storage and outbox delivery
- migrations, test runtime and release gates

## Stack

- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- Docker Compose
- Pytest

## Local run

From `backend`:

```bash
docker compose up -d db minio api
docker compose exec api alembic upgrade head
docker compose exec api pytest -q tests/integration
```

## Quality gate

Primary local gate:

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

Workspace shortcut:

```powershell
.\workspace.cmd test-backend-gate
```

## Important docs

- `TESTING.md`
- `QUALITY_GATE.md`
- `RELEASE.md`
- `PRODUCTION_CHECKLIST.md`
- `ARCHITECTURE.md`
- `OBSERVABILITY.md`
- `OBSERVABILITY_CHEATSHEET.md`
- `INCIDENT_RUNBOOKS.md`

Production env validation:

```bash
python scripts/validate_production_env.py --env-file .env
```

## Repository role

This repository is intentionally isolated from frontend/mobile/workspace repositories.

Do not use a parent git root for backend changes; the backend folder is the git root by design.
