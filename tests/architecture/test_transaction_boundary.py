from __future__ import annotations

import re
from pathlib import Path


COMMIT_PATTERNS = (
    re.compile(r"\buow\.commit\s*\("),
    re.compile(r"\bself\.session\.commit\s*\("),
    re.compile(r"\bsession\.commit\s*\("),
)


def _application_root() -> Path:
    return Path(__file__).resolve().parents[2] / "app" / "modules"


def test_no_commit_calls_in_application_layer() -> None:
    root = _application_root()
    violations: list[str] = []

    for file_path in sorted(root.glob("*/application/**/*.py")):
        text = file_path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in COMMIT_PATTERNS):
                rel = file_path.relative_to(root.parents[1])
                violations.append(f"{rel}:{line_no}: {line.strip()}")

    assert not violations, (
        "Transaction boundary contract failed. Commit is allowed only in router/UoW scope:\n"
        + "\n".join(violations)
    )
