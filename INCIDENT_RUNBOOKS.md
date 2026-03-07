# Incident Runbooks

Operational runbooks for the backend critical flows.

Use these after `v1.0.0` baseline together with:

- `OBSERVABILITY.md`
- `PRODUCTION_CHECKLIST.md`
- `RELEASE.md`

## 1. Auth incident

Typical symptoms:

- users cannot log in
- spike in `401/403` around `/api/v1/auth/login`
- repeated `auth.login.failed` in logs

Primary signals:

- `auth.login.failed`
- `auth.refresh.failed`
- `http.request.failed` on auth routes

First checks:

```powershell
docker compose logs --tail=200 api | Select-String "auth.login|auth.refresh|http.request"
curl -fsS https://<api-host>/health
```

Check environment integrity:

```powershell
python scripts/validate_production_env.py --env-file .env
```

What to verify:

1. `JWT_SECRET` was not rotated accidentally without deploy coordination.
2. target user exists in the correct `company_id`.
3. user is active and has the expected role.
4. database connectivity is healthy.
5. rate limiting is not being mistaken for credential failure.

Safe recovery actions:

1. fix broken env and restart API if the issue is configuration-related
2. restore user access through normal admin flow
3. in non-production only, reseed dev users:

```powershell
docker compose exec -e APP_ENV=dev api python -m app.scripts.seed_dev
```

Do not:

- change JWT settings ad hoc on a live node without coordinated rollout
- edit production users directly in SQL unless application recovery path is impossible

## 2. Installer sync incident

Typical symptoms:

- installer app/web workspace shows stale data
- sync loops, reset-required responses, or event failures
- admins report offline queue not clearing

Primary signals:

- `installer.sync.requested`
- `installer.sync.completed`
- `installer.sync.event_failed`
- sync health alerts / sync risk issues

First checks:

```powershell
docker compose logs --tail=200 api | Select-String "installer.sync"
docker compose logs --tail=200 sync-health | Select-String "sync_health"
```

Admin/API checks:

- `GET /api/v1/admin/sync/stats`
- `GET /api/v1/admin/sync/states`
- `GET /api/v1/admin/sync/health/summary`
- `POST /api/v1/admin/sync/health/run`

What to verify:

1. specific installer has a valid `installer_sync_state`
2. `ack_cursor` advances and `next_cursor` is not stuck
3. event failures are business-validation failures, not transport failures
4. installer is linked correctly and still assigned to the project/doors

Safe recovery actions:

1. run sync health manually:

```powershell
docker compose exec api python -m app.scripts.run_sync_health
```

2. reset one installer state through admin API:
- `POST /api/v1/admin/sync/states/{user_id}/reset`
- or legacy `POST /api/v1/admin/sync/reset/{installer_id}`

3. if local/dev data is broken, reseed:

```powershell
docker compose exec -e APP_ENV=dev api python -m app.scripts.seed_dev
```

Do not:

- delete `sync_change_log` or `installer_sync_state` manually as a first response
- bypass assignment/business checks just to force one client through sync

## 3. Project import incident

Typical symptoms:

- upload/import returns `422`
- imports partially succeed or repeatedly fail
- latest import review shows `FAILED` or `PARTIAL`

Primary signals:

- `project.import.started`
- `project.import.completed`
- `project.import.failed`
- `project.import.retry_completed`

First checks:

```powershell
docker compose logs --tail=200 api | Select-String "project.import"
```

Admin/API checks:

- `GET /api/v1/admin/projects/{project_id}/doors/import-history`
- `GET /api/v1/admin/projects/{project_id}/doors/import-runs/{run_id}`
- `GET /api/v1/admin/projects/import-runs/failed-queue`
- `POST /api/v1/admin/projects/{project_id}/doors/import-runs/{run_id}/retry`
- `POST /api/v1/admin/projects/import-runs/retry-failed`

What to verify:

1. file format is supported and base64 payload is valid
2. mapping profile is correct for source file
3. required columns/required row values are actually present
4. idempotency hit is not being misread as a failed import
5. company plan limits did not block the import

Safe recovery actions:

1. use `analyze` mode first
2. inspect diagnostics and errors preview from import run details
3. retry via stored import-run retry endpoints instead of re-uploading blindly
4. if plan limit blocked import, resolve limit before retrying

Do not:

- patch imported rows manually in SQL
- re-run the same broken file repeatedly without reviewing diagnostics

## 4. Outbox / delivery incident

Typical symptoms:

- journals stay pending
- delivery webhooks do not update message status
- failed delivery count rises in reports

Primary signals:

- `journal.send.requested`
- `journal.send.enqueued`
- `outbox.batch.locked`
- `outbox.message.sent`
- `outbox.message.failed`

First checks:

```powershell
docker compose logs --tail=200 outbox-worker | Select-String "outbox."
docker compose logs --tail=200 api | Select-String "webhooks/outbox|twilio|outbox."
```

Admin/API checks:

- `GET /api/v1/admin/outbox`
- `GET /api/v1/admin/outbox/summary`
- `GET /api/v1/admin/outbox/{outbox_id}`
- `POST /api/v1/admin/outbox/{outbox_id}/retry`

What to verify:

1. outbox worker is running
2. message channel and payload are correct
3. SMTP/Twilio config is valid
4. webhook callbacks reach API and update provider status
5. fallback-to-email behavior is happening as expected for WhatsApp failures

Safe recovery actions:

1. validate env:

```powershell
python scripts/validate_production_env.py --env-file .env
```

2. inspect failed message in admin outbox endpoint
3. fix provider/env issue
4. retry failed outbox message through admin API

Do not:

- mark messages as sent manually in DB
- retry the whole queue blindly if failure is caused by invalid provider config

## 5. Escalation rule

Escalate beyond routine ops when:

1. incident spans more than one company/tenant
2. database integrity is suspected
3. migration side effects are involved
4. repeated failures continue after config/runtime recovery

In those cases, stop making ad hoc fixes and move to controlled hotfix/release procedure from `RELEASE.md`.
