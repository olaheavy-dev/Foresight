"""Money in any currency: ISO 4217 exponents, exact parsing, formatting, currency detection.

docs/07 §4.13: `amount_minor` is an integer in the currency's ISO 4217 minor unit. The exponent is
looked up, never assumed; parsing is exact (Decimal, never float); fractional minor units are an
error, not a rounding.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from backend.finance_core.types import Money, Question

# ISO 4217 minor-unit exponents (subset in use plus common neighbours; unknown codes are rejected).
ISO4217_EXPONENT: dict[str, int] = {
    "GBP": 2, "EUR": 2, "USD": 2, "INR": 2, "CAD": 2, "AUD": 2, "NZD": 2, "CHF": 2, "SEK": 2,
    "NOK": 2, "DKK": 2, "PLN": 2, "CZK": 2, "HUF": 2, "SGD": 2, "HKD": 2, "ZAR": 2, "NGN": 2,
    "KES": 2, "GHS": 2, "AED": 2, "SAR": 2, "CNY": 2, "MXN": 2, "BRL": 2, "TRY": 2,
    "JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "ISK": 0, "UGX": 0, "XOF": 0, "XAF": 0,
    "KWD": 3, "BHD": 3, "OMR": 3, "JOD": 3, "TND": 3, "LYD": 3,
}  # fmt: skip

# Symbols that identify exactly one currency.
UNAMBIGUOUS_SYMBOLS: dict[str, str] = {"£": "GBP", "€": "EUR", "₹": "INR", "₦": "NGN", "₩": "KRW"}
# Symbols shared by several currencies: never guessed, the user is asked (docs/06 H13).
AMBIGUOUS_SYMBOLS: dict[str, tuple[str, ...]] = {
    "$": ("USD", "CAD", "AUD", "NZD", "SGD", "HKD", "MXN"),
    "kr": ("SEK", "NOK", "DKK", "ISK"),
    "¥": ("JPY", "CNY"),
}


class MoneyError(ValueError):
    """An amount that cannot be represented exactly, or an unknown currency."""


def exponent(currency: str) -> int:
    try:
        return ISO4217_EXPONENT[currency.upper()]
    except KeyError as exc:
        raise MoneyError(f"Unknown or unsupported currency code: {currency!r}") from exc


def add(a: Money, b: Money) -> Money:
    """Add two amounts. Mixing currencies is an error, never a silent conversion (V-20)."""
    if a.currency != b.currency:
        raise MoneyError(f"Cannot add {a.currency} and {b.currency}")
    return Money(a.amount_minor + b.amount_minor, a.currency)


_STRIP = re.compile(r"[\s  '’]")


def parse_amount(text: str, currency: str, decimal_sep: str = ".", group_sep: str = ",") -> int:
    """Parse a statement amount into integer minor units, exactly.

    Handles currency symbols and codes, leading/trailing minus, brackets for negatives, trailing
    CR (credit, +) / DR (debit, -) markers, and the given separators. Raises MoneyError when the
    amount has more fractional digits than the currency allows or cannot be parsed.
    """
    raw = text.strip()
    if not raw:
        raise MoneyError("Empty amount")
    negative = False
    upper = raw.upper()
    if upper.endswith("CR"):
        raw = raw[:-2]
    elif upper.endswith("DR"):
        raw, negative = raw[:-2], True
    raw = raw.strip()
    if raw.startswith("(") and raw.endswith(")"):
        raw, negative = raw[1:-1], not negative
    raw = raw.replace(currency.upper(), "").replace(currency.lower(), "")
    for symbol in list(UNAMBIGUOUS_SYMBOLS) + list(AMBIGUOUS_SYMBOLS):
        raw = raw.replace(symbol, "")
    raw = _STRIP.sub("", raw)
    if raw.startswith("+"):
        raw = raw[1:]
    elif raw.startswith("-") or raw.startswith("−"):
        raw, negative = raw[1:], not negative
    elif raw.endswith("-"):
        raw, negative = raw[:-1], not negative
    if group_sep:
        raw = raw.replace(group_sep, "")
    if decimal_sep != ".":
        if "." in raw:
            raise MoneyError(
                f"Unexpected '.' in amount {text!r} (decimal separator is {decimal_sep!r})"
            )
        raw = raw.replace(decimal_sep, ".")
    if not re.fullmatch(r"\d+(\.\d+)?", raw):
        raise MoneyError(f"Not an amount: {text!r}")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:  # pragma: no cover - regex guards this
        raise MoneyError(f"Not an amount: {text!r}") from exc
    scaled = value.scaleb(exponent(currency))
    if scaled != scaled.to_integral_value():
        raise MoneyError(f"{text!r} has more decimal places than {currency} allows")
    minor = int(scaled)
    return -minor if negative else minor


def format_money(amount_minor: int, currency: str, grouping: str = "thousands") -> str:
    """Render minor units with the currency's exponent, e.g. 123456 GBP → '£1,234.56'.

    grouping: 'thousands' (1,234,567) or 'lakh' (12,34,567). Display only; never re-parsed.
    """
    exp = exponent(currency)
    symbol = {v: k for k, v in UNAMBIGUOUS_SYMBOLS.items()}.get(currency.upper(), "")
    sign = "−" if amount_minor < 0 else ""
    units, frac = divmod(abs(amount_minor), 10**exp) if exp else (abs(amount_minor), 0)
    digits = str(units)
    if grouping == "lakh" and len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = [head[max(i - 2, 0) : i] for i in range(len(head), 0, -2)][::-1]
        digits = ",".join(groups + [tail])
    else:
        digits = f"{units:,}"
    body = f"{digits}.{frac:0{exp}d}" if exp else digits
    prefix = symbol if symbol else ""
    suffix = "" if symbol else f" {currency.upper()}"
    return f"{sign}{prefix}{body}{suffix}"


def detect_currency(
    *,
    currency_column_values: Iterable[str] = (),
    amount_samples: Iterable[str] = (),
    header_text: str = "",
    profile_currency: str | None = None,
    home_currency: str,
) -> tuple[str | None, str, Question | None]:
    """Currency detection ladder (docs/00 §6c.2).

    1. a currency column with one valid ISO code; 2. an unambiguous symbol or ISO code in the
    amounts or header; 3. the matched FormatProfile's currency; 4. the workspace home currency.
    An ambiguous symbol ($, kr, ¥) with no stronger evidence returns a Question instead of a guess.
    Returns (currency or None, provenance, question or None).
    """
    codes = {v.strip().upper() for v in currency_column_values if v and v.strip()}
    codes = {c for c in codes if c in ISO4217_EXPONENT}
    if len(codes) == 1:
        return codes.pop(), "column", None
    text = " ".join(list(amount_samples)) + " " + header_text
    found = {code for sym, code in UNAMBIGUOUS_SYMBOLS.items() if sym in text}
    found |= {code for code in ISO4217_EXPONENT if re.search(rf"\b{code}\b", text)}
    if len(found) == 1:
        return found.pop(), "symbol", None
    ambiguous = [sym for sym in AMBIGUOUS_SYMBOLS if sym in text]
    if profile_currency:
        return profile_currency, "profile", None
    if ambiguous:
        sym = ambiguous[0]
        options = AMBIGUOUS_SYMBOLS[sym]
        question = Question(
            kind="currency",
            prompt=f"This file uses {sym}. Which currency is it?",
            options=options,
            preselected=None,
        )
        return None, "ambiguous", question
    return home_currency, "home_default", None
