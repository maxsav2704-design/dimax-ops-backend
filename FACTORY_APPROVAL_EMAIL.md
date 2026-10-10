# Factory Price Invitation Email

The existing invitation endpoint accepts optional `send_email: true`. The
default remains false. Invitation creation, replacement of the old link and
outbox insertion commit together. `email_outbox_id` means queued, not delivered
and not factory-confirmed. No price is activated by sending or opening email.

## Deployment Requirements

- Set `PUBLIC_APP_BASE_URL` to the application's externally reachable HTTPS URL.
  Localhost, private IP addresses and HTTP links cannot be emailed by this path.
- Deploy the public approval API too, set the frontend's `NEXT_PUBLIC_API_BASE_URL`
  to that externally reachable HTTPS API and configure its allowed origin.
  Changing only the invitation URL will not make a localhost API reachable.
- Configure the existing SMTP settings and `EMAIL_ENABLED=true`.
- Provision `FACTORY_APPROVAL_EMAIL_KEY` in the API and outbox worker environment
  (or their `.env`): base64 encoding of 32 cryptographically random bytes. Keep
  it outside Git, logs, database exports and the JWT signing key. No default key
  is supplied. The rates email settings read the same `.env` convention as the
  application without changing unrelated configuration.
- Run the existing outbox worker. API requests do not call SMTP synchronously.
- The production compose supervises the worker with `restart: unless-stopped`
  and `python -m app.workers.outbox_health`. The marker is refreshed only after
  a queue pass commits, including an empty pass. The probe rejects missing,
  malformed, stale, future or dead-process markers. The ten-minute freshness
  window accommodates a batch of twenty SMTP operations; it is not an email
  delivery deadline. Alert on unhealthy status: Docker restart policy restarts
  exited processes, not a live process that merely reports unhealthy. Inspect
  queue failures and pending age separately; a healthy worker can still have
  SMTP/provider failures.
- Keep the same key while invitations await delivery. Replacing the key makes
  queued ciphertext unreadable and invalidates outstanding mailbox codes. Drain
  the queue and revoke/reissue pending verification invitations before rotation;
  do not rotate with pending code challenges. Deliberately revoke/reissue
  affected invitations before rotation. Do not recover links from public logs.

## Mailbox Verification

New confirmations require a six-digit code requested explicitly using
`POST /api/v1/public/price-approvals/request-code` with the invitation token.
The code goes only to the invitation's stored recipient, never an address from
the public request. The response means QUEUED, not delivered, and has expiry and
resend timestamps. No code or full recipient address is returned to the browser.

`POST /confirm` now requires a valid `verification_code` in addition to the
existing version, snapshot, name and explicit consent. Missing/wrong/expired
codes return 403 without approving prices. Deploy the API and approval page
together. There is no production or development bypass for legacy clients.

Codes live for at most ten minutes (never beyond invitation expiry). The shared
database/company lock enforces sixty seconds between requests, ten requests and
five wrong attempts per invitation, across processes. Resending invalidates the
old challenge, not the attempt counter. Failed attempts commit before returning
403. Request limits require an admin to verify the contact and issue a new link.

The database stores a keyed HMAC bound to tenant, invitation, recipient, snapshot
and challenge. The outbox stores an AES-GCM sealed token/code/challenge with a
different payload kind. Workers reject old, expired, revoked, locked, altered or
cross-tenant challenges; generic previews and SMTP errors never expose the code.
Code messages contain no invitation link. API and worker must share the key.

The new `mailbox_verified_at` is recorded atomically with the factory decision.
Existing decisions remain unchanged with NULL evidence, including their past
earnings. Exact confirmation retries remain idempotent after code expiry while
the invitation itself is valid; preview can recover an ambiguous result.
Migration 0069 refuses rollback after any challenge request, protecting evidence
and attempt budgets. Never roll an active API back to link-only confirmation.

## Delivery and Recovery

The outbox stores an AES-256-GCM sealed token and link base, authenticated against
company and invitation identity. Generic outbox previews never include the link.
The worker rechecks the actual recipient, tenant, snapshot, latest version,
company activity, expiration, revocation and pending decision before sending.
Its price-company lock remains held through SMTP submission. Invalid invitations
are terminal failures; SMTP failures use existing bounded outbox retries. Factory
email errors are generic so provider exceptions cannot expose bearer links.

SMTP acceptance sets the queue item to SENT, not proof of receipt or reading.
A crash after SMTP acceptance but before database commit can cause a duplicate
email on retry; this is not exactly-once transport. The duplicated link still
targets the same version and confirmation remains repeat-safe.

Use Operations to inspect/retry failed email. Retrying a revoked, superseded or
expired invitation will not send it: create a replacement after checking its
recipient. A lost API response must be reconciled in invitation/queue history,
not blindly replayed, since a new invitation invalidates the previous link.

The letter contains text plus an HTML review button, not an attachment, invoice,
signature request for completed work or a copy of the complete price table.
The letter is currently English; the review page supports EN/RU/HE. Existing
journal PDF delivery is unchanged. Factory prices and site acceptance remain
separate workflows.

## Remaining Security and Release Gates

Possession of the link reveals the proposed prices but no longer authorizes a
new confirmation on its own. A code verifies control of the named mailbox, not
legal identity, signing authority or a certified electronic signature. Admins
must independently check that the contact represents the factory. Public HTTPS/DNS, real SMTP
delivery, sender authentication and recipient contact verification must be
accepted before production use. No production credentials are created here.

Integration tests use only `dimax_acceptance_tests`; the opt-in `DIMAX_FACTORY_MAILPIT=1`
case asserts the Mailpit SMTP host/port and removes only its own test message.

## Local Process-Level Acceptance

The workspace `docker-compose.acceptance.delivery.yml` is an opt-in overlay for
local Mailpit capture, not production SMTP. From the workspace root, using
PowerShell 7:

```powershell
.\scripts\prepare-acceptance-mail.ps1
docker compose -f docker-compose.acceptance.yml -f docker-compose.acceptance.delivery.yml --profile delivery up -d --wait api outbox-worker
$env:DIMAX_FACTORY_DELIVERY_CHECK = '1'
node --test scripts/factory-delivery.test.mjs
```

Before enabling the main local worker, inspect any existing acceptance outbox:
enabling the worker processes all eligible messages in that local database.
The preparation script creates a random 32-byte key in the ignored
`acceptance/.factory-mail/shared.env`, restricts access to the current Windows
user and SYSTEM, rejects reparse paths, reuses an existing valid key and refuses
to replace an invalid key automatically. API and worker mount the same file
read-only; the key is not emitted, committed or placed in Docker command-line
arguments. Do not delete this directory as cache: existing queued mail and
verification challenges depend on it. Back up the key in an approved secret
store separately from database dumps.

The opt-in process test uses its own `dimax_factory_delivery_<random>` database,
migrations from zero, labeled disposable API/worker containers and Mailpit-only
SMTP. It logs in through real HTTP, queues an invitation, extracts the link from
the captured multipart email, queues a real random code with the worker stopped,
restarts API/worker and confirms the exact version using the delivered code.
It verifies replay safety, no activation/earnings and an unchanged main ledger.
It stops its worker and removes only its messages, containers and database.
Transient authentication state lives only in the disposable container's `/tmp`.
No mocked sender, fixed verification code or authentication bypass is used.

The reserved HTTPS name `factory.example.test` exists only in these disposable
test containers. Requests use the internal API; this proves the process/SMTP
chain, not public DNS/TLS reachability or actual mailbox receipt. The normal
localhost acceptance UI retains its production-style HTTPS invitation guard.
It is intentionally unable to email a localhost invitation to a real factory.
