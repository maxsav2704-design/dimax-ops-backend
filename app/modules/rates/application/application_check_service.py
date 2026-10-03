from app.modules.rates.application.approval_service import approval_snapshot_matches
from app.modules.rates.application.reconciliation_dto import PriceApplicationCheck, PriceApplicationIssue


class FactoryPriceApplicationCheckService:
    @staticmethod
    def get(uow, *, price_list, summary, at) -> PriceApplicationCheck:
        blockers, review = [], []
        def block(code, count=1):
            if count:
                blockers.append(PriceApplicationIssue(code=code, count=count))
        def note(code, count):
            if count:
                review.append(PriceApplicationIssue(code=code, count=count))

        receipt = uow.price_lists.confirmed_approval(price_list.company_id, price_list.id)
        if price_list.status != "CONFIRMED":
            block("NOT_CONFIRMED")
        elif receipt is None:
            block("CONFIRMATION_MISSING")
        elif (receipt.confirmed_at < receipt.created_at or receipt.confirmed_at > at
              or not approval_snapshot_matches(uow, price_list, receipt)):
            block("CONFIRMATION_MISMATCH")
        # An expired sharing link does not undo an already recorded factory decision.
        latest = uow.price_lists.latest_confirmed_version(price_list.company_id)
        if price_list.status == "CONFIRMED" and price_list.version < latest:
            block("SUPERSEDED_CONFIRMED")

        lines = uow.price_lists.items(price_list.company_id, price_list.id)
        block("NO_ITEMS", int(not lines))
        prices = {(row.kind, row.door_type_id or row.addon_type_id): row for row in lines}
        unavailable, changed, missing = 0, 0, {"DOOR": 0, "ADDON": 0}
        for work in uow.price_lists.required_work(price_list.company_id, price_list.id):
            if not work["available"]:
                unavailable += 1
                continue
            proposed = prices.get((work["kind"], work["target_id"]))
            if proposed is None:
                missing[work["kind"]] += 1
            elif proposed.name != work["name"] or proposed.unit != work["unit"]:
                changed += 1
        block("MISSING_DOOR_PRICES", missing["DOOR"])
        block("MISSING_ADDON_PRICES", missing["ADDON"])
        block("UNAVAILABLE_WORK", unavailable)
        block("CATALOG_CHANGED", changed)
        block("INSTALLER_SURCHARGES", summary.door_surcharges)
        note("LEGACY_DIFFERENCES", summary.different)
        note("DOOR_SNAPSHOTS", summary.door_snapshots)
        note("SCHEDULED_RATES", summary.scheduled_rates)
        note("UNACCRUED_WORK", summary.pending_addon_facts)
        note("URGENCY_CHARGES", summary.urgency_surcharges)
        return PriceApplicationCheck(status="BLOCKED" if blockers else "REVIEW_REQUIRED" if review else "VERIFIED",
            confirmed_at=receipt.confirmed_at if receipt else None, blockers=blockers, review=review)
