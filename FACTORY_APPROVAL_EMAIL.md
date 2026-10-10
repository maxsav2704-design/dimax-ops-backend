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

Tests use only `dimax_acceptance_tests`; the opt-in `DIMAX_FACTORY_MAILPIT=1`
case asserts the Mailpit SMTP host/port and removes only its own test message.
