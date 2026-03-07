from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


def detect_repo() -> str | None:
    env_repo = os.environ.get("GITHUB_REPOSITORY")
    if env_repo:
        return env_repo

    proc = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    url = (proc.stdout or "").strip()
    if not url:
        return None

    if url.startswith("git@github.com:"):
        tail = url.split("git@github.com:", 1)[1]
        return tail[:-4] if tail.endswith(".git") else tail

    for prefix in ("https://github.com/", "http://github.com/"):
        if url.startswith(prefix):
            tail = url[len(prefix):]
            return tail[:-4] if tail.endswith(".git") else tail

    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify GitHub branch protection required checks."
    )
    parser.add_argument("--repo", help="owner/repo (optional, auto-detected if omitted)")
    parser.add_argument("--branch", default="main")
    parser.add_argument(
        "--required-check",
        action="append",
        dest="required_checks",
        default=[],
    )
    parser.add_argument(
        "--token",
        help="GitHub token (optional, otherwise GH_TOKEN/GITHUB_TOKEN or gh auth token).",
    )
    return parser.parse_args()


def get_token(cli_token: str | None) -> str | None:
    if cli_token:
        return cli_token
    env_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if env_token:
        return env_token

    proc = subprocess.run(
        ["gh", "auth", "token"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        token = (proc.stdout or "").strip()
        return token or None
    return None


def fetch_protection(repo: str, branch: str, token: str) -> dict:
    url = f"https://api.github.com/repos/{repo}/branches/{branch}/protection"
    req = urllib.request.Request(
        url=url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    args = parse_args()
    repo = args.repo or detect_repo()
    if not repo:
        print("Cannot detect repository. Pass --repo owner/repo.", file=sys.stderr)
        return 2

    token = get_token(args.token)
    if not token:
        print(
            "No GitHub token found. Use --token or set GH_TOKEN/GITHUB_TOKEN or gh auth.",
            file=sys.stderr,
        )
        return 2

    required_checks = args.required_checks or ["Backend Tests / quality-gate"]

    try:
        data = fetch_protection(repo, args.branch, token)
    except urllib.error.HTTPError as e:
        print(f"GitHub API error: HTTP {e.code}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return 1

    checks = data.get("required_status_checks") or {}
    contexts = checks.get("contexts") or []
    strict = bool(checks.get("strict"))

    missing = [c for c in required_checks if c not in contexts]
    if missing:
        print("Branch protection is missing required checks:", file=sys.stderr)
        for item in missing:
            print(f"- {item}", file=sys.stderr)
        return 1
    if not strict:
        print("Branch protection strict mode is disabled.", file=sys.stderr)
        return 1

    print(f"Branch protection is valid for {repo}/{args.branch}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
