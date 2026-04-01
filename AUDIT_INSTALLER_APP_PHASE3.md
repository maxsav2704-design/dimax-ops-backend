# DIMAX Installer Audit — Phase 3 Security

Status legend: `PASS` / `FAIL`

Audit basis:
- live API against local backend on `http://127.0.0.1:8001`
- DB spot-checks via `psql`
- targeted code inspection for missing rate-limit middleware

Seed credentials used:
- company: `ddb0ce5a-686d-4cb0-8d5d-87f38e6cf6ee`
- admin: `admin@dimax.dev / admin12345`
- installer_1: `installer1@dimax.dev / installer12345`
- installer_2: `installer2@dimax.dev / installer12345`

## 3.1 Refresh session integrity

| # | Check | Command / action | Pass criterion | Status | Notes |
|---|---|---|---|---|---|
| 3.1.1* | `refresh_sessions.token_hash` stored as bcrypt, not raw/derived JWT string | `SELECT token_hash FROM refresh_sessions LIMIT 3;` | Values start with `$2b$` | FAIL | Actual values are fixed-length SHA-256 hex strings; code inspection confirms `_hash_token()` uses `hashlib.sha256` |
| 3.1.2* | Refresh rotation revokes previous session with `ROTATION` | `POST /api/v1/auth/refresh`; inspect `refresh_sessions` | Previous row has `revoked_at` and `revoke_reason='ROTATION'`; new row is active | PASS | Live DB shows old session revoked with `ROTATION` and `replaced_by_jti`; new row remains active |
| 3.1.3* | Refresh replay attack returns `401 REFRESH_TOKEN_REUSE` | Reuse same refresh token twice | `401 {code:'REFRESH_TOKEN_REUSE'}` and all sessions revoked | PASS | Carried over from Phase 2 auth block; live-verified there |
| 3.1.4* | Access token lifetime is 15 minutes | Decode JWT payload and compare `exp - iat` | `900` seconds exactly | FAIL | Live access token currently uses `1800` seconds |

## 3.2 Rate limiting

| # | Check | Command / action | Pass criterion | Status | Notes |
|---|---|---|---|---|---|
| 3.2.1 | Login rate limit `5 / 15 min` | 6 invalid `POST /api/v1/auth/login` attempts | First 5 => `401`, 6th => `429` | FAIL | Live check returned `401` on all 6 attempts |
| 3.2.2 | Installer sync rate limit `30 / min` | 31 `POST /api/v1/installer/sync` calls with empty batch | Request `31` returns `429` | FAIL | Live check returned `200` for all 31 calls |
| 3.2.3 | Import rate limit `5 / hour` | Inspect import routes + limiter config | Import endpoints protected by limiter or proxy policy | FAIL | No rate-limiting middleware/config found in app code; import routes have no limiter hooks |

## 3.3 Data isolation

| # | Check | Command / action | Pass criterion | Status | Notes |
|---|---|---|---|---|---|
| 3.3.1* | `installer_1` does not see `installer_2` projects | Compare `GET /api/v1/installer/projects` with two real installer tokens | Responses are scoped to assigned doors only | PASS | Live: installer_1 saw `Audit Leakage Project`; installer_2 saw empty list |
| 3.3.2* | Installer token on admin route returns `403 FORBIDDEN_SCOPE` | `GET /api/v1/admin/projects` with installer token | `403 {code:'FORBIDDEN_SCOPE'}` | FAIL | Actual response is `403 {code:'FORBIDDEN', message:'Admin only'}` |
| 3.3.3* | Installer project payload does not leak developer email | `GET /api/v1/installer/projects/{id}` and inspect payload | No `email` field anywhere in installer payload | PASS | Carried over from Phase 2 leakage block; live grep remains empty |
| 3.3.4* | Installer project payload does not leak `surcharge_pct` | `GET /api/v1/installer/projects/{id}` and inspect payload | No `surcharge_pct` or surcharge finance fields | PASS | Carried over from Phase 2 leakage block; live grep remains empty |
| 3.3.5 | `journal_events` are not exposed via installer API | `GET /api/v1/installer/journal` | `404` because route does not exist for installer | PASS | Live response is `404 NOT_FOUND` |

## Phase 3 result

- Total checks: `12`
- PASS: `7`
- FAIL: `5`
- Critical PASS: `5`
- Critical FAIL: `3`
- Non-critical PASS: `2`
- Non-critical FAIL: `2`

## Major release blockers from Phase 3

1. Refresh sessions are not bcrypt-hashed:
   - `token_hash` currently uses SHA-256 hex, not bcrypt
2. Access token lifetime is too long:
   - current `exp - iat = 1800`, audit requires `900`
3. Installer → admin scope code is still inconsistent:
   - `FORBIDDEN` instead of `FORBIDDEN_SCOPE`

## Pre-production security debt

1. Login rate limiting is absent
2. Installer sync rate limiting is absent
3. Import rate limiting is absent
