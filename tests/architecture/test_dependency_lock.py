from __future__ import annotations

import re
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PIN_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)$")
DIRECT_NAME_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_dependency_constraints_are_complete_and_exact() -> None:
    direct_lines = _requirement_lines(BACKEND_ROOT / "requirements.txt")
    constraint_lines = _requirement_lines(BACKEND_ROOT / "constraints.txt")

    pins: dict[str, str] = {}
    for line in constraint_lines:
        match = PIN_PATTERN.fullmatch(line)
        assert match is not None, f"Dependency constraint is not exact: {line}"
        normalized_name = _normalize(match.group(1))
        assert normalized_name not in pins, f"Duplicate dependency pin: {match.group(1)}"
        pins[normalized_name] = match.group(2)

    direct_names = set()
    for line in direct_lines:
        match = DIRECT_NAME_PATTERN.match(line)
        assert match is not None, f"Unsupported direct requirement: {line}"
        direct_names.add(_normalize(match.group(1)))

    assert direct_names <= pins.keys(), (
        "Direct requirements missing from constraints: "
        f"{sorted(direct_names - pins.keys())}"
    )


def test_dockerfile_enforces_constraints_and_non_root_runtime() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "-c constraints.txt -r requirements.txt" in dockerfile
    assert "pip check" in dockerfile
    assert "build-essential" not in dockerfile
    assert "USER 10001:10001" in dockerfile
