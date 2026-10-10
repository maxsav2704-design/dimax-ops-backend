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
  queued ciphertext unreadable; drain the queue or deliberately revoke/reissue
  affected invitations before rotation. Do not recover links from public logs.

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

Possession of the link still authorizes confirmation. Email delivery does not
verify the representative's identity; mailbox OTP/account verification is a
separate required review before external rollout. Public HTTPS/DNS, real SMTP
delivery, sender authentication and recipient contact verification must be
accepted before production use. No production credentials are created here.

Tests use only `dimax_acceptance_tests`; the opt-in `DIMAX_FACTORY_MAILPIT=1`
case asserts the Mailpit SMTP host/port and removes only its own test message.
