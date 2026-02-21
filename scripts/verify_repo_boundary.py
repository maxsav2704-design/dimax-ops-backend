from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _git_toplevel(cwd: Path) -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git rev-parse failed")
    return Path(proc.stdout.strip()).resolve()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify git root matches backend repository boundary."
    )
    parser.add_argument(
        "--path",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository path to validate (default: backend root).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_path = Path(args.path).resolve()

    try:
        actual_root = _git_toplevel(repo_path)
    except Exception as exc:
        print(f"[repo-boundary] ERROR: {exc}")
        return 1

    expected_root = repo_path
    if actual_root != expected_root:
        print("[repo-boundary] ERROR: git root mismatch")
        print(f"[repo-boundary] expected: {expected_root}")
        print(f"[repo-boundary] actual:   {actual_root}")
        print(
            "[repo-boundary] Fix: run this check from backend root or re-initialize git in backend."
        )
        return 1

    print(f"[repo-boundary] OK: {actual_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
