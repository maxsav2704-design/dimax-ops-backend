# Commercial contracts and confirmation

Factory-to-DIMAX preparation only. This is separate from the existing
`factory_price_lists`, whose `installer_price` is installer remuneration.

The first increment supports OWNER-only contract drafts and append-only price
draft versions for ILS prices excluding VAT. Every operation rechecks the active
OWNER profile inside its UoW. The database only allows DRAFT, and responses
explicitly report `factory_confirmed=false`, `usable_for_billing=false`.
Standalone draft snapshots are not factory decisions. Confirmation of an exact
terms/price pair is separate; there are no activation, billing, execution or
earning operations in this module.

Routes:
- GET/POST `/api/v1/admin/accounting/contracts`
- GET/POST `/api/v1/admin/accounting/contracts/{contract_id}/prices`
- GET `/api/v1/admin/accounting/contracts/{contract_id}/prices/{price_id}`
- GET/POST `/api/v1/admin/accounting/contracts/{contract_id}/terms`
- GET `/api/v1/admin/accounting/contracts/{contract_id}/terms/{terms_id}`

Create requests require a request UUID; a changed payload with the same UUID
conflicts. Price creation additionally checks `expected_latest_version`.
The tenant lock serializes allocation of versions until UoW commit.
Audit failure rolls back the draft. Saved versions have no edit/delete route.

`INSTALLATION` and `STAGE` target existing door types; `ADDON` targets an add-on
type. Labels and units are catalog snapshots. STAGE codes describe proposed
rates, not executable door plans. A catalog may offer a full-installation price
and stage prices; later work-plan/billing allocation must select a mutually
exclusive basis, never charge both.

The contract retains its original display name/reference. Separate terms
versions snapshot the factory legal name, registration number, address,
optional contract contact, proposed dates, full/stage installation billing
basis and payment/retention clauses. Each version records its author ID/name,
server timestamp, change reason and agreement reference. Terms creation uses
the same OWNER checks, tenant lock, request replay and optimistic version check
as price drafts. Migration 0085 additionally rejects UPDATE/DELETE of terms
history at database level. There is no automatic backfill of existing contracts.

Contact details are informational, not an approved factory representative,
accountant address or notification destination. No permission is granted by
entering an email. Payment/retention clauses are verbatim text, not executable
formulas; unresolved due-date anchors, business-day rules, withholding bases
and tax rounding are not invented. The agreed period is 10th inclusive to next
10th exclusive in Asia/Jerusalem; ILS prices exclude VAT. No tax rate is assumed.

Terms and prices have independent draft histories; confirmation never silently
binds an old price to newer terms. Project exceptions, verified counterparty
identity and effective selection remain later work.
Proposed dates are not effective dates. Installer earnings never read this table.

Invented rates live in `tests/fixtures/commercial_demo_prices.json`. Tests use a
synthetic company in an isolated database whose name ends in `_tests` with
APP_ENV=test. Contracts created by that runtime receive durable `is_demo=true`
from the server; the client cannot remove that marker. No seed endpoint or
fixture startup import exists, and no production company is populated.
Any future activation/export must enforce the marker. No current export reads
this module. Normal-environment OWNER requests can prepare real drafts only;
invented fixtures must never be submitted there.

Migration 0085 follows 0084, which depends on workspace migration 0083_import_inbox.
Deployment must include that predecessor; it is another agent's work and is not
included in this module's commit. Isolated acceptance commands target only the
disposable database. Do not assume restoring an ordinary container is read-only:
the existing local API startup command runs `alembic upgrade head` against its
configured database and mounts workspace sources. Inspect command, mounts and
current revision before stopping/restarting it; pending migrations need a
separate deployment/backup decision. See the workspace acceptance record for
actual migration and restoration results.

## Exact-version confirmation (0086)

OWNER reviews the latest terms and price together, then sends an invitation to
the existing OWNER-approved factory contact. Contract contact fields do not grant
approval authority. A request UUID, exact snapshot hash, both version IDs and the
expected contact ID protect retry and stale-review handling. Admin responses
contain no token or code. The invitation and mailbox challenge use purpose-bound
AES-GCM outbox payloads and the existing verification limits (five attempts,
ten code requests, 60-second resend delay, ten-minute codes).

Endpoints below `.../contracts/{contract_id}`:
- GET `approval-preview?terms_id=...&price_id=...`
- GET/POST `approvals`; GET `approvals/{id}`; POST `approvals/{id}/revoke`

Public POST `/api/v1/public/commercial-approvals/{preview,request-code,confirm}`
is rate-limited and has no-store responses. The `/commercial-approval#token`
page removes the fragment, sends no admin JWT/cookies, requires the full name,
mailbox code and explicit consent to both displayed version numbers and digest.
Opening a link has no confirming effect. A replaced contact, either newer draft,
revocation or expiry invalidates a pending invitation, including queued email.
Exact retries cannot duplicate a recorded decision. Historical decisions remain
in OWNER history after expiry or later amendments; they are not silently revoked.

Migration 0086 adds tenant/contract composite references, request uniqueness,
one pending invitation per contract and one confirmed decision per pair. The
invitation identity/snapshot and terminal states are immutable; an invited price
cannot be rewritten through its header or items. Terms already have a blanket
immutability trigger. Downgrade refuses to erase any approval or its audit trail.
Audit failure rolls back decision and evidence atomically. The external-audit
constraint adds only COMMERCIAL_APPROVAL confirmation and preserves the existing
import-inbox actor rule.

Draft DTO status and `factory_confirmed=false` describe the standalone proposal,
not an effective contract. Pair-specific confirmation status belongs to
`commercial_approvals`; `usable_for_billing` remains false on every response.
No installer ledger, price list, work status or journal signature is changed.
Demo contracts may exercise this flow only in APP_ENV=test, remain marked in
the page/email/receipt and never become real billing evidence. Real delivery
requires configured encrypted email and a public HTTPS application URL.
