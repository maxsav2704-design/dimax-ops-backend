# Repository Boundaries Plan

Current issue: git root is above project directory, which mixes unrelated files with backend history and CI scope.

## Recommended Target

- Separate repository root = `.../DIMAX Operations Suite/backend`

## Migration Plan (Safe, Step by Step)

1. Create a new empty GitHub repository for backend.
2. In `backend` directory, initialize a standalone git repo:

```bash
cd "C:\Users\Hi-tech\.vscode\DIMAX Operations Suite\backend"
git init --initial-branch main
git add .
git commit -m "Initial backend repository"
git remote add origin <backend-repo-url>
git push -u origin main
```

3. Configure branch protection using `QUALITY_GATE.md`.
4. Keep old top-level repo as archive or remove backend subtree from it later.

## Optional: Preserve Full History

If you need old commit history for `backend` only, use `git filter-repo` on a clone and publish filtered history to the new backend repository.

## Why This Matters

- Clean `git status` and PR diffs.
- Correct workflow discovery under `.github/workflows`.
- Smaller CI scope and faster checks.
