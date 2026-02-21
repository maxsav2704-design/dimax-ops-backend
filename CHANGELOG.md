# Changelog

## [v1.0.0-rc1] - 2026-02-21

### Added
- Integration test suite for RBAC, validation, OpenAPI contract, audit coverage, reports, dashboard, files, projects, sync, outbox, and end-to-end core flow.
- Architecture contract test: `tests/architecture/test_module_structure.py`.
- Repository boundary verification: `scripts/verify_repo_boundary.py`.
- Backup/restore smoke script: `scripts/db_backup_restore_smoke.py`.
- Operational docs: `RELEASE.md`, `PRODUCTION_CHECKLIST.md`.

### Changed
- Standardized module layering to `api/application/domain/infrastructure` for key modules (`journal`, `dashboard`, `reports`, `projects`, `addons`, `sync`, `identity`, `installers`, `outbox`, `files`).
- Unified API error envelope and OpenAPI error schemas for `400/401/403/404/409/422`.
- Explicit OpenAPI response contracts for binary endpoints and `204 No Content` endpoints.
- CI quality gate expanded with required jobs:
  - `repo-boundary`
  - `backup-restore-smoke`
  - `architecture-contract`
  - `api-contract`
  - `error-contract`
  - `integration`
  - `migration-smoke`

### Fixed
- Duplicate unique index on `installer_rates(company_id, installer_id, door_type_id)` dropped while preserving canonical unique constraint via migration `0022_installer_rates_drop_duplicate_unique_index.py`.
