# Quality Gate

## CI Gate

Workflow: `.github/workflows/backend-tests.yml`

Required job:

- `Backend Tests / quality-gate`

Upstream jobs included in `quality-gate`:

- `Backend Tests / repo-boundary`
- `Backend Tests / backup-restore-smoke`
- `Backend Tests / architecture-contract`
- `Backend Tests / api-contract`
- `Backend Tests / error-contract`
- `Backend Tests / integration`
- `Backend Tests / migration-smoke`

This job must pass for every PR before merge.

## GitHub Settings (Repository Admin)

1. Open `Settings -> Branches -> Add branch protection rule`.
2. Select target branch (for example `main`).
3. Enable `Require a pull request before merging`.
4. Enable `Require status checks to pass before merging`.
5. Mark `Backend Tests / quality-gate` as required.
6. Enable `Require branches to be up to date before merging`.

## Optional Automation (GitHub CLI)

If you have repo admin rights, you can apply branch protection via script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_branch_protection.ps1 -Repo "<owner>/<repo>" -Branch "main"
```

Dry-run (print API payload only):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_branch_protection.ps1 -Repo "<owner>/<repo>" -DryRun
```

Cross-platform Python alternative (useful when PowerShell is restricted by ConstrainedLanguage):

```bash
python scripts/setup_branch_protection.py --repo "<owner>/<repo>" --branch "main"
```

Python dry-run:

```bash
python scripts/setup_branch_protection.py --repo "<owner>/<repo>" --dry-run
```

## ConstrainedLanguage Risks

If PowerShell runs in ConstrainedLanguage and blocks script execution:

- Branch protection may stay unapplied and PR merges won't be blocked by required checks.
- Team may assume gate is active from docs, while repository settings still allow unsafe merges.
- Manual setup gets delayed, creating a gap where failing tests can still reach `main`.

Mitigation:

- Use the Python script above or run the `gh api` command directly.
- Verify protection after apply: repository branch settings must show `Backend Tests / quality-gate` as required.

CLI verification:

```bash
python scripts/verify_branch_protection.py --repo "<owner>/<repo>" --branch "main"
```

## Local Pre-PR Check

Run before pushing:

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

Workspace shortcut from repo root:

```powershell
.\workspace.cmd test-backend-gate
```

This shortcut uses the isolated workspace test runtime (`docker-compose.workspace.test.yml`) and avoids dev `--reload` restarts during verification.

`error-contract` validates unified API error envelope (`error.code`, `error.message`, `error.details`) for key `400/401/403/404/409/422` paths.

`architecture-contract` validates module folder shape against architecture conventions with explicit allowlist exceptions.

`repo-boundary` validates that git root is exactly the backend folder.

`backup-restore-smoke` validates PostgreSQL dump/restore path after migrations.
