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

Create requests require a request UUID; a changed payload with the same UUID
conflicts. Price creation additionally checks `expected_latest_version`.
The tenant lock serializes allocation of versions until UoW commit.
Audit failure rolls back the draft. Saved versions have no edit/delete route.

`INSTALLATION` and `STAGE` target existing door types; `ADDON` targets an add-on
type. Labels and units are catalog snapshots. STAGE codes describe proposed
rates, not executable door plans. A catalog may offer a full-installation price
and stage prices; later work-plan/billing allocation must select a mutually
exclusive basis, never charge both.

At this stage the contract stores the proposed factory name and reference.
Legal party registration, payment/retention terms, project exceptions, approval,
and effective price selection belong to subsequent increments. `proposed_from`
is a requested date only. It does not make a draft effective.

Invented rates live in `tests/fixtures/commercial_demo_prices.json`. Tests use a
synthetic company in an isolated database whose name ends in `_tests` with
APP_ENV=test. Contracts created by that runtime receive durable `is_demo=true`
from the server; the client cannot remove that marker. No seed endpoint or
fixture startup import exists, and no production company is populated.
Any future activation/export must enforce the marker. No current export reads
this module. Normal-environment OWNER requests can prepare real drafts only;
invented fixtures must never be submitted there.

Migration 0084 follows the current workspace migration 0083_import_inbox.
Deployment must include that predecessor; it is another agent's work and is not
included in this module's commit. No normal/demo DB migration is performed by
the acceptance checks. See the workspace acceptance record for actual results.
