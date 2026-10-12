from pathlib import Path

import yaml


def test_error_contract_ci_prepares_database_before_db_backed_tests() -> None:
    workflow_path = (
        Path(__file__).resolve().parents[2]
        / ".github/workflows/backend-tests.yml"
    )
    jobs = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["jobs"]
    steps = jobs["error-contract"]["steps"]
    commands = [step.get("run", "") for step in steps]

    start = commands.index("docker compose up -d --wait db")
    migrate = commands.index(
        "docker compose run --rm --no-deps api alembic upgrade head"
    )
    test = next(
        index for index, command in enumerate(commands)
        if "pytest -q" in command
    )
    assert start < migrate < test

    cleanup = next(step for step in steps if step.get("run") == "docker compose down -v")
    assert steps.index(cleanup) > test
    assert cleanup.get("if") == "always()"


def test_offline_migration_ci_owns_a_separate_database_before_cleanup() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github/workflows/backend-tests.yml"
    steps = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["jobs"]["migration-smoke"]["steps"]
    database = "dimax_offline_evidence_migration_tests"
    create = next(step for step in steps if step.get("id") == "offline-evidence-db")
    run = next(step for step in steps if "api python -m scripts.db_offline_evidence_migration_smoke" in step.get("run", ""))
    cleanup = next(step for step in steps if step.get("run") == f"docker compose exec -T db dropdb -U postgres {database}")
    assert create["run"] == f"docker compose exec -T db createdb -U postgres {database}"
    assert steps.index(create) < steps.index(run) < steps.index(cleanup)
    assert "-e APP_ENV=test" in run["run"]
    assert "-e DIMAX_OFFLINE_EVIDENCE_MIGRATION=1" in run["run"]
    assert f"@db:5432/{database}" in run["run"]
    assert cleanup["if"] == "always() && steps.offline-evidence-db.outcome == 'success'"
