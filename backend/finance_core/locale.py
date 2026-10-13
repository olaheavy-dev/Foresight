"""Locale packs (data, not code) and number/date format inference (docs/00 §6c, docs/07 §4.14).

The pack *content* (narration codes, categories, payday conventions…) lives in
`finance_core/locale_packs/<pack>.yaml`. This module only loads and validates it, and infers number
and date formats from file evidence. Ambiguity is never resolved silently: it becomes a Question.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import holidays as holidays_lib
import yaml

from backend.finance_core.types import Question

DEFAULT_MONTHS: dict[str, int] = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9,
    "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12,
}  # fmt: skip


class LocalePackError(ValueError):
    pass


@dataclass(frozen=True)
class LocalePack:
    key: str  # "uk", "in"
    country: str  # ISO 3166 alpha-2 for python-holidays, e.g. "GB"
    subdivision: str | None  # e.g. "ENG", "KA"
    default_currency: str
    locale: str  # e.g. "en-GB"
    date_order: str  # preferred order when a file is ambiguous: "DMY" | "MDY" | "YMD"
    decimal_sep: str = "."
    group_sep: str = ","
    grouping: str = "thousands"  # "thousands" | "lakh"
    month_names: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_MONTHS))
    # Everything else (narration codes, categories, payday conventions, protected categories,
    # wording) is pack data consumed by other modules; kept verbatim.
    extra: dict[str, Any] = field(default_factory=dict)


_REQUIRED = ("key", "country", "default_currency", "locale", "date_order")


def load_locale_pack(text: str) -> LocalePack:
    """Parse and validate a locale pack from YAML text (the caller reads the file)."""
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise LocalePackError("Locale pack must be a mapping")
    missing = [k for k in _REQUIRED if k not in data]
    if missing:
        raise LocalePackError(f"Locale pack is missing: {', '.join(missing)}")
    if data["date_order"] not in ("DMY", "MDY", "YMD"):
        raise LocalePackError("date_order must be DMY, MDY or YMD")
    numbers = data.get("numbers") or {}
    months = dict(DEFAULT_MONTHS)
    months.update({str(k).lower(): int(v) for k, v in (data.get("month_names") or {}).items()})
    known = set(_REQUIRED) | {"subdivision", "numbers", "month_names"}
    return LocalePack(
        key=str(data["key"]),
        country=str(data["country"]),
        subdivision=data.get("subdivision"),
        default_currency=str(data["default_currency"]).upper(),
        locale=str(data["locale"]),
        date_order=str(data["date_order"]),
        decimal_sep=str(numbers.get("decimal_sep", ".")),
        group_sep=str(numbers.get("group_sep", ",")),
        grouping=str(numbers.get("grouping", "thousands")),
        month_names=months,
        extra={k: v for k, v in data.items() if k not in known},
    )


def holiday_dates(pack: LocalePack, years: Iterable[int]) -> frozenset[date]:
    """Public holidays for the pack's country/subdivision (python-holidays; no network)."""
    calendar = holidays_lib.country_holidays(
        pack.country, subdiv=pack.subdivision, years=list(years)
    )
    return frozenset(calendar.keys())


# --------------------------------------------------------------------------- number format


@dataclass(frozen=True)
class NumberFormat:
    decimal_sep: str
    group_sep: str
    grouping: str  # "thousands" | "lakh" | "none"


_NUM = re.compile(r"[0-9][0-9.,\s '’]*[0-9]|[0-9]")


def infer_number_format(
    samples: Sequence[str], currency_exponent: int
) -> tuple[NumberFormat | None, Question | None]:
    """Infer decimal and grouping separators from amount strings (docs/07 §4.14 step 2).

    The last separator followed by exactly `currency_exponent` digits is the decimal separator.
    Inconsistent evidence across samples yields a Question; nothing is coerced.
    """
    decimal_votes: set[str] = set()
    group_votes: set[str] = set()
    lakh = False
    for raw in samples:
        m = _NUM.search(raw or "")
        if not m:
            continue
        token = re.sub(r"[\s '’]", "", m.group(0))
        seps = [(i, ch) for i, ch in enumerate(token) if ch in ".,"]
        if not seps:
            continue
        last_i, last_ch = seps[-1]
        tail = len(token) - last_i - 1
        if currency_exponent > 0 and tail == currency_exponent:
            decimal_votes.add(last_ch)
            groups = [ch for _, ch in seps[:-1]]
        else:
            groups = [ch for _, ch in seps]
        group_votes.update(groups)
        if groups:
            int_part = token[:last_i] if tail == currency_exponent else token
            parts = re.split(r"[.,]", int_part)
            if len(parts) >= 3 and all(len(p) == 2 for p in parts[1:-1]) and len(parts[-1]) == 3:
                lakh = True
    if len(decimal_votes) > 1 or (decimal_votes & group_votes):
        return None, Question(
            kind="decimal_separator",
            prompt="This file mixes decimal marks. Which one marks pence/cents?",
            options=(".", ","),
        )
    decimal = decimal_votes.pop() if decimal_votes else ("," if group_votes == {"."} else ".")
    group = group_votes.pop() if len(group_votes) == 1 else ("," if decimal == "." else ".")
    grouping = "lakh" if lakh else "thousands"
    return NumberFormat(decimal_sep=decimal, group_sep=group, grouping=grouping), None


# --------------------------------------------------------------------------- date format


@dataclass(frozen=True)
class DateFormat:
    """A parsed date layout. order: DMY/MDY/YMD; month_text: month written as a name."""

    order: str
    month_text: bool = False

    def describe(self) -> str:
        return f"{self.order}{'-name' if self.month_text else ''}"


_DATE_SPLIT = re.compile(r"[/\-.\s]+")


def _fields(text: str) -> list[str]:
    return [p for p in _DATE_SPLIT.split(text.strip().rstrip(",")) if p]


def parse_date(text: str, fmt: DateFormat, months: dict[str, int] | None = None) -> date:
    """Parse a date with a known layout. Month names (incl. 'Sept') come from the pack."""
    months = months or DEFAULT_MONTHS
    parts = _fields(text.split("T")[0])
    if len(parts) < 3:
        raise ValueError(f"Not a date: {text!r}")
    parts = parts[:3]
    if fmt.month_text:
        name_idx = next(i for i, p in enumerate(parts) if not p.isdigit())
        month = months.get(parts[name_idx].lower().rstrip("."))
        if month is None:
            raise ValueError(f"Unknown month in {text!r}")
        nums = [int(p) for i, p in enumerate(parts) if i != name_idx]
        if fmt.order == "YMD":
            year, day = nums[0], nums[1]
        else:
            day, year = nums[0], nums[1]
    else:
        a, b, c = (int(p) for p in parts)
        if fmt.order == "DMY":
            day, month, year = a, b, c
        elif fmt.order == "MDY":
            month, day, year = a, b, c
        else:
            year, month, day = a, b, c
    if year < 100:
        year += 2000
    return date(year, month, day)


def infer_date_format(
    samples: Sequence[str], pack: LocalePack, saved: DateFormat | None = None
) -> tuple[DateFormat | None, Question | None]:
    """Resolve the date layout from evidence (docs/07 §4.14 step 3).

    Saved/built-in format wins. Otherwise: a month name ⇒ name layout; a four-digit first field ⇒
    YMD; any first field > 12 ⇒ DMY; any second field > 12 ⇒ MDY. Still ambiguous ⇒ a Question
    with the pack's order pre-selected; the locale alone never commits the batch.
    """
    if saved is not None:
        return saved, None
    rows = [_fields(s.split("T")[0]) for s in samples if s and s.strip()]
    rows = [r[:3] for r in rows if len(r) >= 3]
    if not rows:
        return None, None
    if any(not p.isdigit() for r in rows for p in r):
        order = "YMD" if all(len(r[0]) == 4 and r[0].isdigit() for r in rows) else "DMY"
        return DateFormat(order=order, month_text=True), None
    if all(len(r[0]) == 4 for r in rows):
        return DateFormat(order="YMD"), None
    first_gt = any(int(r[0]) > 12 for r in rows)
    second_gt = any(int(r[1]) > 12 for r in rows)
    if first_gt and second_gt:
        return None, Question(
            kind="date_order",
            prompt="The dates in this file don't follow one order. Please check the file.",
            options=("DMY", "MDY"),
        )
    if first_gt:
        return DateFormat(order="DMY"), None
    if second_gt:
        return DateFormat(order="MDY"), None
    return None, Question(
        kind="date_order",
        prompt="Is 03/04 the 3rd of April or March 4th in this file?",
        options=("DMY", "MDY"),
        preselected=pack.date_order if pack.date_order in ("DMY", "MDY") else None,
    )
