# Quality Gate

## CI Gate

Workflow: `.github/workflows/backend-tests.yml`

Required job:

- `Backend Tests / integration`

This job must pass for every PR before merge.

## GitHub Settings (Repository Admin)

1. Open `Settings -> Branches -> Add branch protection rule`.
2. Select target branch (for example `main`).
3. Enable `Require a pull request before merging`.
4. Enable `Require status checks to pass before merging`.
5. Mark `Backend Tests / integration` as required.
6. Enable `Require branches to be up to date before merging`.

## Local Pre-PR Check

Run before pushing:

```bash
docker compose up -d db minio
docker compose run --rm api alembic upgrade head
docker compose run --rm api pytest -q tests/integration
docker compose down -v
```
