# Testing

## Prerequisites

- Docker Desktop is running.
- Workdir: `backend`.

## Local Run (Fast)

```bash
docker compose up -d db minio api
docker compose exec api alembic upgrade head
docker compose exec api pytest -q tests/integration
```

## Local Run (CI Equivalent)

```bash
docker compose up -d db minio
docker compose run --rm api alembic upgrade head
docker compose run --rm api pytest -q tests/integration
docker compose down -v
```

## When Dependencies Change

If `requirements.txt` changed, rebuild `api` image before running `docker compose run`:

```bash
docker compose build api
```
