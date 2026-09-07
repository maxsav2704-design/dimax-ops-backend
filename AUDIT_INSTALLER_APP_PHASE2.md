# DIMAX Installer Audit — Phase 2 API

Status legend: `PASS` / `FAIL`

Audit basis:
- live API against local backend on `http://127.0.0.1:8001`
- route presence from `/openapi.json`
- DB spot-checks via `psql`

Seed credentials used:
- company: `ddb0ce5a-686d-4cb0-8d5d-87f38e6cf6ee`
- admin: `admin@dimax.dev / admin12345`
- installer: `installer1@dimax.dev / installer12345`

## 2.1 Auth endpoints

| # | Check | Command / action | Pass criterion | Status | Notes |
|---|---|---|---|---|---|
| 2.1.1* | `POST /auth/login` returns `access_token` and `refresh_token` | `POST /api/v1/auth/login` with valid seed creds | `200 + {access_token, refresh_token, user:{id, role, language}}` | PASS | Live response now contains `user:{id, role, language, display_name}` |
| 2.1.2* | `POST /auth/login` with wrong password returns `401` | `POST /api/v1/auth/login` with `password=wrong12` | `401 {error:{code:'INVALID_CREDENTIALS'}}` | PASS | Live response now returns `401 INVALID_CREDENTIALS` |
| 2.1.3* | `POST /auth/refresh` returns new token pair and rotates old refresh | `POST /api/v1/auth/refresh` with valid refresh token; inspect DB | `200 + new pair; old refresh marked ROTATION` | PASS | Rotation now updates `refresh_sessions` and marks the old row with `revoke_reason='ROTATION'` |
| 2.1.4* | Reusing refresh token returns `401 REFRESH_TOKEN_REUSE` | Use same refresh token twice; inspect DB | `401 {code:'REFRESH_TOKEN_REUSE'}; all user sessions revoked` | PASS | Live API now returns `401 REFRESH_TOKEN_REUSE`; reuse path is enforced |
| 2.1.5* | `GET /auth/me` returns current user profile | `GET /api/v1/auth/me` with access token | `200 + {id, role, display_name, language, company_id}` | PASS | Live payload now includes `display_name` and `language` |
| 2.1.6* | `POST /auth/logout` revokes refresh token | `POST /api/v1/auth/logout`; then `POST /api/v1/auth/refresh` with old refresh token | `200 OK; reuse of refresh token => 401` | PASS | Logout now revokes active refresh sessions and old refresh returns `401 REFRESH_TOKEN_REUSE` |

## 2.2 Installer — Workspace and Calendar

| # | Check | Command / action | Pass criterion | Status | Notes |
|---|---|---|---|---|---|
| 2.2.1* | `GET /installer/workspace` returns today's workload | `GET /openapi.json`; `GET /api/v1/installer/workspace` | `200 + {today_tasks, priority_tasks, earnings_today, problem_projects}` | PASS | Live route now exists and returns non-empty workload blocks |
| 2.2.2* | Workspace does not leak another installer's tasks | `GET /api/v1/installer/workspace` as installer_1 | Only installer_1 tasks returned | PASS | Covered by integration test `test_installer_workspace_does_not_leak_other_installer_data` |
| 2.2.3* | `GET /installer/calendar/events` returns only current installer's events for period | Create 1 event for installer_1 and 1 for installer_2; `GET /api/v1/installer/calendar/events?...` | `200 + only events of current installer` | PASS | Live check passed: installer_1 saw only own event, installer_2 saw only own event |
| 2.2.4 | Calendar events contain `waze_deep_link` | Create project-bound event with address; inspect response | `waze_deep_link` present when address exists | PASS | Installer calendar payload now exposes both `waze_url` and `waze_deep_link` |

## 2.3 Installer — Projects and Doors

| # | Check | Command / action | Pass criterion | Status | Notes |
|---|---|---|---|---|---|
| 2.3.1* | `GET /installer/projects` returns only assigned projects | Insert one project/door for installer_1 and one for installer_2; `GET /api/v1/installer/projects` | Only projects assigned to current installer | PASS | Live check passed |
| 2.3.2* | `GET /installer/projects/:id` returns `developer.whatsapp_deep_link` and `waze_deep_link` | `GET /api/v1/installer/projects/{project_id}` on assigned project | Both deep links present in response | PASS | `developer.whatsapp_deep_link` and `address_details.waze_deep_link` are present |
| 2.3.3* | Installer API does not leak `client_price`, `margin`, `surcharge_pct` | `GET /api/v1/installer/projects/{project_id}` and inspect payload | Financial fields absent | PASS | Live installer payload no longer exposes `our_price`, `client_price`, `installer_price`, `margin` or `surcharge_pct`; admin route still returns financial fields |
| 2.3.4* | Installer API does not return `developer.email` | `GET /api/v1/installer/projects/{project_id}` | `developer.email` absent | PASS | Live payload does not include developer email |
| 2.3.5* | `PATCH /installer/doors/:id/status` with valid transition works | `GET /openapi.json`; `PATCH /api/v1/installer/doors/{door_id}/status` | `200`; status changes; `version +1` | PASS | Endpoint now exists and valid transitions pass |
| 2.3.6* | Forbidden transition returns `422 INVALID_TRANSITION` | `PATCH /api/v1/installer/doors/{door_id}/status` with invalid transition | `422 {code:'INVALID_TRANSITION', meta:{...}}` | PASS | Covered by integration test `test_door_status_installer_cannot_set_cancelled` |
| 2.3.7* | Setting status to `INSTALLED` creates `completed_work` | Use audit status endpoint then check DB | Ledger row created with snapshots | PASS | Covered by integration tests; `completed_work.entry_type='ORIGINAL'` is created |
| 2.3.8* | Installer cannot change another installer's door | Try updating installer_2 door as installer_1 | `403 {code:'DOOR_NOT_ASSIGNED'}` | PASS | Covered by integration test `test_door_status_installer_cannot_change_other_door` |

## 2.4 Installer — Issues and Earnings

| # | Check | Command / action | Pass criterion | Status | Notes |
|---|---|---|---|---|---|
| 2.4.1* | `POST /installer/issues` creates issue and switches door to `ISSUE_OPEN` | `GET /openapi.json`; `POST /api/v1/installer/issues` | `201`; door status becomes `ISSUE_OPEN` | PASS | Endpoint now exists; covered by integration test `test_installer_can_create_issue_and_open_door` |
| 2.4.2* | `GET /installer/earnings/summary` does not leak `client_rate` and `margin` | `GET /api/v1/installer/earnings/summary?period=day` | `client_rate`, `margin`, `surcharge_pct` absent | PASS | Live grep on earnings payload returned empty output for `client|margin|surcharge` |
| 2.4.3* | Earnings summary excludes superseded `ORIGINAL` rows | Create correction and query earnings summary | Summary reflects correction, not stale original | PASS | Covered by integration test `test_installer_earnings_summary_excludes_superseded_originals` |
| 2.4.4 | Monthly earnings summary returns `weekly_breakdown` | `GET /api/v1/installer/earnings/summary?period=month` | `weekly_breakdown` present | PASS | Covered by integration test `test_installer_monthly_earnings_summary_returns_weekly_breakdown` |

## 2.5 Standard contracts

| # | Check | Command / action | Pass criterion | Status | Notes |
|---|---|---|---|---|---|
| 2.5.1* | List endpoints return pagination object | `GET /api/v1/installer/projects?page=1&per_page=10`; inspect `issues` and `sync-queue` too | `{items, pagination:{page, per_page, total, total_pages}}` | PASS | Installer list endpoints now return shared pagination metadata with defaults `page=1`, `per_page=25` |
| 2.5.2* | Errors use standard error object | Trigger auth and route errors | `{error:{code, message, field?, meta?}}` | PASS | Central handler now maps domain and validation errors to `field/meta` and keeps route code paths uniform |
| 2.5.3* | Request without token returns `401` | `GET /api/v1/installer/projects` without `Authorization` | `401 {code:'UNAUTHORIZED'}` | PASS | Live check passed |
| 2.5.4* | ADMIN token to `/installer/*` returns `403 FORBIDDEN_SCOPE` | `GET /api/v1/installer/workspace` with admin token | `403 {code:'FORBIDDEN_SCOPE'}` | PASS | `require_installer` now enforces installer-only scope centrally and live `/installer/workspace` returns `FORBIDDEN_SCOPE` |

## Phase 2 result

- Total checks: `26`
- PASS: `26`
- FAIL: `0`
- Critical PASS: `24`
- Critical FAIL: `0`
- Non-critical PASS: `2`
- Non-critical FAIL: `0`

## Major release blockers from Phase 2

No open API release blockers remain in Phase 2 after Block 4 alignment.
