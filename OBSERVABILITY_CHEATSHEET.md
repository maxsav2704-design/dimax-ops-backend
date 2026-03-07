# Observability Cheat Sheet

Use this as the first operational view after deploy or during incident triage.

## Core log fields

Always filter by:

- `event`
- `request_id`
- `company_id`
- `installer_id`
- `project_id`
- `outbox_id`

## Priority event groups

Auth:

- `auth.login.failed`
- `auth.login.succeeded`
- `auth.refresh.failed`
- `auth.refresh.succeeded`

Installer sync:

- `installer.sync.requested`
- `installer.sync.completed`
- `installer.sync.event_failed`

Project import:

- `project.import.started`
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

HTTP:

- `http.request.completed`
- `http.request.failed`

## Minimum dashboard panels

1. `HTTP failures by path`
2. `Auth failures by company_id`
3. `Installer sync failures by installer_id`
4. `Project import failures by project_id`
5. `Outbox failed messages by channel`
6. `Outbox backlog batch duration / count`

## First questions during incident triage

Auth:

- do we see a burst of `auth.login.failed` for one company or user?

Installer sync:

- do `installer.sync.requested` and `installer.sync.completed` pair correctly?
- are there any `installer.sync.event_failed` rows for the target installer?

Project import:

- did import start?
- did it finish or fail?
- was retry successful?

Outbox:

- do `journal.send.enqueued` events appear without `outbox.message.sent` or `outbox.message.failed`?

## Fast local grep examples

```bash
docker compose logs api | rg '"event": "auth.login.failed"'
docker compose logs api | rg '"event": "project.import.failed"'
docker compose logs outbox-worker | rg '"event": "outbox.message.failed"'
docker compose logs sync-health | rg '"event": "installer.sync.event_failed"'
docker compose logs api | rg '"request_id": "<request-id>"'
```

## Alerting baseline

Alert if these repeat above normal baseline:

- `http.request.failed`
- `auth.login.failed`
- `installer.sync.event_failed`
- `project.import.failed`
- `outbox.message.failed`

## Rule

Identify the failing boundary first:

1. request path
2. company scope
3. worker activity
4. retry outcome

Only then move to incident recovery steps from `INCIDENT_RUNBOOKS.md`.
