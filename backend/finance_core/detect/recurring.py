"""Recurring obligations, price changes and subscription overlap (docs/07 §4.3, roadmap ENG-01).

Outflows are grouped by counterparty and category; a group recurs when it has ≥ 3 occurrences with
gaps inside a cadence band and amounts within ±15 % of the median (variable bills). Seasonal
monthly obligations (council tax: 10 instalments Apr–Jan) keep their active months; with less than
12 months of history the pack's seasonal default is used and flagged as an assumption.

Monthly direct debits and standing orders are collected on the next working day when their date
falls on a weekend or bank holiday, so the statement shows a drifting day. Given the calendar, the
detector looks for the nominal day and shift that explain the most observed dates; it records the
pack's debit shift only when that explains strictly more dates than taking each date as it is.
Card payments never move.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from backend.finance_core.calendar import clamp_day, shift
from backend.finance_core.categorise.pack import CategorisationPack, contains_phrase
from backend.finance_core.types import (
    Cadence,
    Categorisation,
    Channel,
    FlowKind,
    RecurringObligation,
    Transaction,
    WorkingDayShift,
)

MIN_OCCURRENCES = 3
AMOUNT_BAND = 0.15
PRICE_CHANGE = 0.05
STABLE_PRICE = 0.02  # price changes are only meaningful for fixed-price services
_CADENCE_BANDS: tuple[tuple[Cadence, int, int], ...] = (
    (Cadence.WEEKLY, 6, 8),
    (Cadence.MONTHLY, 26, 34),
    (Cadence.QUARTERLY, 85, 95),
    (Cadence.ANNUAL, 355, 375),
)
# flows that never become recurring obligations here (income has its own detector)
_EXCLUDED = {
    FlowKind.INCOME,
    FlowKind.REFUND,
    FlowKind.TRANSFER_OWN,
    FlowKind.INFLOW_UNCONFIRMED,
    FlowKind.TRANSFER_FROM_UNTRACKED,
    FlowKind.BETTING_RETURN,
}


@dataclass(frozen=True)
class PriceChange:
    obligation_key: str
    previous_minor: int
    latest_minor: int
    changed_on: date


@dataclass(frozen=True)
class SubscriptionOverlap:
    family: str
    obligation_keys: tuple[str, ...]
    monthly_total_minor: int


@dataclass(frozen=True)
class RecurringReport:
    obligations: tuple[RecurringObligation, ...]
    price_changes: tuple[PriceChange, ...]
    overlaps: tuple[SubscriptionOverlap, ...]
    assumptions: tuple[str, ...]


def _cadence(gaps: Sequence[int]) -> Cadence | None:
    if not gaps:
        return None
    med = statistics.median(gaps)
    for cadence, lo, hi in _CADENCE_BANDS:
        if lo <= med <= hi:
            inside = sum(lo <= g <= hi for g in gaps)
            # seasonal monthly obligations have one long gap per year (e.g. Jan → Apr)
            if cadence == Cadence.MONTHLY and inside >= len(gaps) - max(1, len(gaps) // 10):
                return cadence
            if inside == len(gaps):
                return cadence
    return None


def _months_between(first: date, last: date) -> list[tuple[int, int]]:
    out = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _active_months(
    dates: Sequence[date], category: str, pack: CategorisationPack, assumptions: list[str]
) -> frozenset[int]:
    span = _months_between(dates[0], dates[-1])
    seen = {(d.year, d.month) for d in dates}
    missing = {m for (y, m) in span if (y, m) not in seen}
    if len(span) >= 12:
        observed = frozenset(d.month for d in dates)
        return observed if missing else frozenset(range(1, 13))
    default = pack.seasonal_defaults.get(category)
    if default is not None:
        assumptions.append(
            f"{category}: fewer than 12 months of history; assumed payments in months "
            f"{sorted(default)} (locale default)"
        )
        return default
    return frozenset(range(1, 13))


_SCHEDULED_CHANNELS = {Channel.DIRECT_DEBIT, Channel.STANDING_ORDER}


def infer_anchor_and_shift(
    rows: Sequence[Transaction], pack: CategorisationPack, holidays: frozenset[date]
) -> tuple[int, WorkingDayShift]:
    """Nominal day of month and weekend/holiday shift that explain the most observed dates.

    Only direct debits and standing orders can move (to the pack's debit shift); everything else
    keeps the most common observed day and no shift. Ties keep no shift, then the most common
    day, so the conservative reading wins unless the calendar clearly explains the drift."""
    dates = [t.posted_on for t in rows]
    counts = Counter(d.day for d in dates)
    mode_day = counts.most_common(1)[0][0]
    channel = Counter(t.channel for t in rows).most_common(1)[0][0]
    if channel not in _SCHEDULED_CHANNELS:
        return mode_day, WorkingDayShift.NONE
    moved = WorkingDayShift(pack.debit_shift)

    def hits(day: int, how: WorkingDayShift) -> int:
        return sum(shift(clamp_day(d.year, d.month, day), how.value, holidays) == d for d in dates)

    best_none = max(range(1, 32), key=lambda day: (hits(day, WorkingDayShift.NONE), counts[day]))
    best_moved = max(range(1, 32), key=lambda day: (hits(day, moved), counts[day]))
    if hits(best_moved, moved) > hits(best_none, WorkingDayShift.NONE):
        return best_moved, moved
    return mode_day, WorkingDayShift.NONE


def _slug(text: str) -> str:
    return "_".join(text.lower().split())[:40] or "unknown"


def detect_recurring(
    txns: Sequence[Transaction],
    cats: Sequence[Categorisation],
    pack: CategorisationPack,
    holidays: frozenset[date] = frozenset(),
) -> RecurringReport:
    """Recurring obligations in a ledger. `holidays` is the locale's bank-holiday set; without it
    only weekends count as non-working days when learning a debit's shift."""
    by_id = {c.transaction_id: c for c in cats}
    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for t in txns:
        c = by_id.get(t.id)
        if t.amount_minor >= 0 or c is None or c.flow_kind in _EXCLUDED:
            continue
        groups[(t.counterparty or t.normalised, c.category_key)].append(t)

    obligations: list[RecurringObligation] = []
    changes: list[PriceChange] = []
    assumptions: list[str] = []
    for (counterparty, category), rows in groups.items():
        rows = sorted(rows, key=lambda t: t.posted_on)
        if len(rows) < MIN_OCCURRENCES:
            continue
        amounts = [-t.amount_minor for t in rows]
        median = statistics.median(amounts)
        in_band = [t for t in rows if abs(-t.amount_minor - median) <= AMOUNT_BAND * median]
        if len(in_band) < MIN_OCCURRENCES:
            continue
        dates = [t.posted_on for t in in_band]
        cadence = _cadence([(b - a).days for a, b in zip(dates, dates[1:], strict=False)])
        if cadence is None:
            continue
        key = f"rob_{_slug(counterparty)}"
        flow = by_id[rows[0].id].flow_kind
        active = (
            _active_months(dates, category, pack, assumptions)
            if cadence == Cadence.MONTHLY
            else frozenset(range(1, 13))
        )
        anchor, how = (
            infer_anchor_and_shift(in_band, pack, holidays)
            if cadence == Cadence.MONTHLY
            else (None, WorkingDayShift.NONE)
        )
        obligations.append(
            RecurringObligation(
                key=key,
                label=counterparty.title(),
                category_key=category,
                flow_kind=flow,
                amount_minor=-int(statistics.median([-t.amount_minor for t in in_band[-3:]])),
                currency=rows[0].currency,
                cadence=cadence,
                anchor_day=anchor,
                active_months=active,
                member_ids=tuple(t.id for t in in_band),
                is_commitment=category in pack.protected_categories or flow == FlowKind.COMMITMENT,
                shift=how,
            )
        )
        # price change: compare the latest payment with the earlier median over ALL rows of the
        # group (a rise above the ±15 % band would otherwise hide itself)
        earlier = [-t.amount_minor for t in rows[:-1]]
        previous = statistics.median(earlier)
        latest = -rows[-1].amount_minor
        stable_before = previous and (max(earlier) - min(earlier)) <= STABLE_PRICE * previous
        if stable_before and abs(latest - previous) / previous >= PRICE_CHANGE:
            changes.append(PriceChange(key, int(previous), latest, rows[-1].posted_on))
            obligations[-1] = replace(obligations[-1], amount_minor=-latest)
    return RecurringReport(
        obligations=tuple(obligations),
        price_changes=tuple(changes),
        overlaps=detect_overlaps(obligations, pack),
        assumptions=tuple(assumptions),
    )


def detect_overlaps(
    obligations: Sequence[RecurringObligation], pack: CategorisationPack
) -> tuple[SubscriptionOverlap, ...]:
    """Two or more active services in one subscription family. An overlap, never a claim of
    non-use."""
    found = []
    for family, members in pack.subscription_families.items():
        hits = [o for o in obligations if any(contains_phrase(o.label.upper(), m) for m in members)]
        if len(hits) >= 2:
            found.append(
                SubscriptionOverlap(
                    family=family,
                    obligation_keys=tuple(o.key for o in hits),
                    monthly_total_minor=sum(-o.amount_minor for o in hits),
                )
            )
    return tuple(found)
