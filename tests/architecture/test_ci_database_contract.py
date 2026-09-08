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
