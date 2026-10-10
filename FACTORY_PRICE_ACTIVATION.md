# Reviewed Factory Price Activation

Confirmation and activation are separate events. A factory representative
confirms a frozen version using the personal invitation and mailbox code.
An authorized company administrator then reviews the transition and starts its
effect for every project. An installer cannot perform either admin action or
choose the rate/earned amount.

## Operator Flow

1. Verify the representative's authority and contact outside the application.
2. Enter the common price list with the change request and agreement reference.
3. Have the representative confirm the exact version using the mailbox code.
4. In Price Lists, inspect reconciliation and the recorded factory decision.
5. Select Apply confirmed prices. Review the active version, blocking issues,
   rate differences and pending work. Enter the reason and explicitly consent.
6. Confirm the effective version/time in the result and company pricing status.
   Installer clients receive the read-only active list through existing sync.

An unconfirmed amendment never changes the active version. Historical decisions
with no mailbox evidence cannot be newly activated; create a new version and
obtain a verified decision. Do not invent or backfill confirmation evidence.
Past effective versions, their quotes and earnings remain intact.

## API Contract

`POST /api/v1/admin/price-lists/{price_list_id}/activate`

```json
{
  "request_id": "unique-client-request-uuid",
  "expected_active_price_list_id": null,
  "reason": "Reviewed initial company-wide transition under agreement ...",
  "reviewed_transition": true
}
```

Use null only for the first activation; otherwise supply the observed active
list UUID. No client-specified start time, company, price or amount is accepted.
OWNER/OPERATIONS must have rate access and active user/company records. FINANCE,
VIEWER, installers, anonymous and foreign-company users cannot activate it.

Within the existing unit of work, the service holds the company lock, checks
permissions, request fingerprint, predecessor, monotonic version, factory
evidence, coverage, catalog and incompatible surcharges. The effective timestamp
comes from the server. Activation and audit commit atomically. The response
contains the activation/approval IDs, list ID, reason, actor and effective time,
with Cache-Control no-store. No confirmation link or mailbox code is returned.

Identical requests return the original receipt, even after a later transition;
reusing the request ID with different content returns 409. Review failures or
changed active versions return 409 without a partial activation. Permission
failures return 403; a foreign/missing list returns 404 to an authorized caller.

## Earnings And Recovery

- Future work uses the price effective at execution, not upload time.
- Old queued offline work without a price version uses the first confirmed list,
  not a later amendment. Missing work prices remain an explicit pricing conflict.
- Existing completed-work amounts and evidence are never repriced by activation.
- Duplicate sync or activation requests must not duplicate earnings/activations.
- No backdating, deactivate/delete switch or downgrade to an old version is
  offered. Correct future prices through a newly confirmed amendment.
- After a lost HTTP response, reload current company pricing and audit history.
  Do not blindly create another transition. The UI locks that submission and
  requests a status review; protocol clients may replay the identical request ID.

## Release Boundary

The test suite exercises JWT login, factory mailbox decision, both activations,
stale predecessor rejection, late offline work and duplicate submissions in a
test database. Browser tests mock API responses and verify the UI contract,
consent and EN/RU/HE layouts; they do not prove external SMTP or physical-device
operation. Production still requires shared email key, supervised delivery,
HTTPS, verified factory contact, device acceptance and a backed-up pilot.
