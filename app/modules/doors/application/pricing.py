from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


_MONEY_QUANT = Decimal("0.01")
_PCT_DENOMINATOR = Decimal("100.00")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CompletionPricing:
    base_client_rate: Decimal
    final_client_rate: Decimal
    final_installer_rate: Decimal


def resolve_completion_pricing(
    *,
    base_client_rate: Decimal,
    base_installer_rate: Decimal,
    surcharge_pct: Decimal,
    apply_surcharge_to_installer: bool,
) -> CompletionPricing:
    multiplier = Decimal(str(surcharge_pct)) / _PCT_DENOMINATOR
    final_client_rate = _money(Decimal(str(base_client_rate)) * multiplier)
    final_installer_rate = _money(Decimal(str(base_installer_rate)))
    if apply_surcharge_to_installer:
        final_installer_rate = _money(final_installer_rate * multiplier)

    return CompletionPricing(
        base_client_rate=_money(Decimal(str(base_client_rate))),
        final_client_rate=final_client_rate,
        final_installer_rate=final_installer_rate,
    )
