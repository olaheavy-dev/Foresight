"""Server-side money display (docs/08 §3.2, §3.2b). Clients never format `minor` themselves."""

from __future__ import annotations

import re

from backend.app.ui_contracts.primitives import MoneyAmount, MoneyValue, Precision
from backend.finance_core.money import exponent, format_money

# Locales whose grouping is lakh/crore (12,34,567); everything else groups in thousands.
LAKH_LOCALES = frozenset({"en-IN", "hi-IN"})


def round_half_up_to_major(amount_minor: int, currency: str) -> int:
    """Whole major units, half away from zero, returned in minor units."""
    unit = int(10 ** exponent(currency))
    whole, rest = divmod(abs(amount_minor), unit)
    if rest * 2 >= unit:
        whole += 1
    return (-1 if amount_minor < 0 else 1) * whole * unit


def display_money(amount_minor: int, currency: str, locale: str, precision: Precision) -> str:
    """'exact' keeps every minor digit (£1,234.56, ¥1,234); 'rounded' shows whole major units
    (£1,235) for projections, which are uncertain."""
    grouping = "lakh" if locale in LAKH_LOCALES else "thousands"
    if precision == "exact":
        return format_money(amount_minor, currency, grouping)
    text = format_money(round_half_up_to_major(amount_minor, currency), currency, grouping)
    exp = exponent(currency)
    return re.sub(rf"\.\d{{{exp}}}(?=( [A-Z]{{3}})?$)", "", text) if exp else text


def money_value(
    amount: MoneyAmount, locale: str, precision: Precision, ref: str | None = None
) -> MoneyValue:
    """Hydrate an exact amount into the client's money value. `minor` is always exact; only the
    display string is rounded."""
    return MoneyValue(
        kind="money",
        minor=amount.amount_minor,
        currency=amount.currency,
        display=display_money(amount.amount_minor, amount.currency, locale, precision),
        precision=precision,
        ref=ref,
    )
