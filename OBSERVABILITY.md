# Observability

Backend now emits structured JSON logs for critical operational flows.

## Request-level logs

Every HTTP request gets:

- `X-Request-ID` header in response
- `http.request.completed`
- `http.request.failed`

Fields include:

- `request_id`
- `method`
- `path`
- `status_code`
- `duration_ms`
- `client_ip`

## Critical flow events

Auth:

- `auth.login.attempt`
- `auth.login.failed`
- `auth.login.succeeded`
- `auth.refresh.failed`
- `auth.refresh.succeeded`
- `auth.logout_refresh.*`
- `auth.logout_all.succeeded`

Installer sync:

- `installer.sync.requested`
- `installer.sync.completed`
- `installer.sync.event_failed`

Project import:

- `project.import.started`
- `project.import.idempotency_hit`
- `project.import.completed`
- `project.import.failed`
- `project.import.retry_completed`

Journal / outbox:

- `journal.send.requested`
- `journal.send.enqueued`
- `outbox.batch.locked`
- `outbox.batch.completed`
- `outbox.message.sent`
- `outbox.message.failed`

## Operational use

Minimum recommendation:

1. Capture stdout/stderr from API and workers.
2. Index logs by `event`, `company_id`, `request_id`, `outbox_id`, `project_id`, `installer_id`.
3. Alert on repeated:
   - `auth.login.failed`
   - `installer.sync.event_failed`
   - `project.import.failed`
   - `outbox.message.failed`

## Note

These logs are observability-only changes. They do not change domain behavior or API contracts.
