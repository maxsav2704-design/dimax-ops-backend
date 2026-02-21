from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


def detect_repo_from_git_remote() -> str | None:
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

    # git@github.com:owner/repo.git
    if url.startswith("git@github.com:"):
        tail = url.split("git@github.com:", 1)[1]
        return tail[:-4] if tail.endswith(".git") else tail

    # https://github.com/owner/repo(.git)
    for prefix in ("https://github.com/", "http://github.com/"):
        if url.startswith(prefix):
            tail = url[len(prefix):]
            return tail[:-4] if tail.endswith(".git") else tail

    return None


def build_payload(required_checks: list[str], required_approvals: int) -> dict:
    return {
        "required_status_checks": {
            "strict": True,
            "contexts": required_checks,
        },
        "enforce_admins": False,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": required_approvals,
        },
        "restrictions": None,
        "required_linear_history": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "block_creations": False,
        "required_conversation_resolution": True,
        "lock_branch": False,
        "allow_fork_syncing": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply GitHub branch protection with required status checks."
    )
    parser.add_argument("--repo", help="owner/repo. If omitted, auto-detected from git remote origin.")
    parser.add_argument("--branch", default="main")
    parser.add_argument(
        "--required-check",
        action="append",
        dest="required_checks",
        default=["Backend Tests / quality-gate"],
        help="Required status check context. Can be passed multiple times.",
    )
    parser.add_argument("--required-approvals", type=int, default=1)
    parser.add_argument(
        "--token",
        help="GitHub token with repo admin permissions. If omitted, uses GH_TOKEN/GITHUB_TOKEN or gh auth.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def apply_with_gh(*, repo: str, branch: str, payload_json: str) -> int:
    auth_check = subprocess.run(
        ["gh", "auth", "status"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if auth_check.returncode != 0:
        return 1

    cmd = [
        "gh",
        "api",
        "--method",
        "PUT",
        "-H",
        "Accept: application/vnd.github+json",
        f"/repos/{repo}/branches/{branch}/protection",
        "--input",
        "-",
    ]
    return subprocess.run(cmd, input=payload_json, text=True, check=False).returncode


def apply_with_token(*, repo: str, branch: str, payload_json: str, token: str) -> int:
    url = f"https://api.github.com/repos/{repo}/branches/{branch}/protection"
    req = urllib.request.Request(
        url=url,
        data=payload_json.encode("utf-8"),
        method="PUT",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            return 0
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"GitHub API error: HTTP {e.code}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"GitHub API request failed: {e}\n")
        return 1


def main() -> int:
    args = parse_args()
    if not 0 <= args.required_approvals <= 6:
        print("required-approvals must be in range 0..6", file=sys.stderr)
        return 2

    payload = build_payload(args.required_checks, args.required_approvals)
    payload_json = json.dumps(payload, indent=2)
    if args.dry_run:
        print(payload_json)
        return 0

    repo = args.repo or detect_repo_from_git_remote()
    if not repo:
        print(
            "Cannot detect repository. Pass --repo owner/repo or set git remote origin.",
            file=sys.stderr,
        )
        return 2

    token = args.token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    if token:
        rc = apply_with_token(
            repo=repo,
            branch=args.branch,
            payload_json=payload_json,
            token=token,
        )
        if rc == 0:
            print(f"Branch protection updated for {repo}/{args.branch} (token)")
            return 0
        print(
            f"Failed to apply branch protection for {repo}/{args.branch} (token)",
            file=sys.stderr,
        )
        return rc

    rc = apply_with_gh(repo=repo, branch=args.branch, payload_json=payload_json)
    if rc == 0:
        print(f"Branch protection updated for {repo}/{args.branch} (gh)")
        return 0

    print(
        "Failed to apply branch protection: provide --token (or GH_TOKEN/GITHUB_TOKEN) or configure gh auth.",
        file=sys.stderr,
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
