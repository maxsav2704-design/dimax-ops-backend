# Commercial drafts

Factory-to-DIMAX preparation only. This is separate from the existing
`factory_price_lists`, whose `installer_price` is installer remuneration.

The first increment supports OWNER-only contract drafts and append-only price
draft versions for ILS prices excluding VAT. Every operation rechecks the active
OWNER profile inside its UoW. The database only allows DRAFT, and responses
explicitly report `factory_confirmed=false`, `usable_for_billing=false`.
There are no approval, activation, billing, execution or earning operations.

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

Terms and prices have independent draft histories; this increment does not
silently bind an old price to newer terms. Future confirmation/activation must
bind the exact contract terms and price versions. Project exceptions, verified
counterparty identity, approval and effective selection remain later work.
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
included in this module's commit. No normal/demo DB migration is performed by
the acceptance checks. See the workspace acceptance record for actual results.
