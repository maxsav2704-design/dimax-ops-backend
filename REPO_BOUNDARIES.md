# Repository Boundaries

## Target Boundary

- Backend git root must be exactly: `.../DIMAX Operations Suite/backend`
- CI/workflows/docs are scoped to this repository root.

## Enforced Contract

- Verification script: `scripts/verify_repo_boundary.py`
- CI check: `Backend Tests / repo-boundary`
- Aggregated gate: `Backend Tests / quality-gate`

If git root drifts above/below backend, `repo-boundary` fails and blocks merge.

## Local Verification

```bash
python scripts/verify_repo_boundary.py
```

Expected output:

- `[repo-boundary] OK: <backend-path>`

## Recovery (if boundary is broken)

1. Go to backend folder:
   - `cd "C:\Users\Hi-tech\.vscode\DIMAX Operations Suite\backend"`
2. Re-initialize backend git root:
   - `git init --initial-branch main`
3. Reconnect remote:
   - `git remote add origin <backend-repo-url>`
4. Push and restore branch protection from `QUALITY_GATE.md`.
