"""Behaviour trends: category spikes and long pay gaps (docs/07 §6.6)."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from backend.finance_core.types import Categorisation, FlowKind, Transaction

WINDOW_DAYS = 30
Z_THRESHOLD = 2.0
MIN_DELTA_MINOR = 2500  # £25 in a two-decimal currency
MIN_DELTA_SHARE = 0.15
LONG_PAY_GAP_DAYS = 35
_SPEND = {FlowKind.SPENDING, FlowKind.FEE, FlowKind.BETTING}


@dataclass(frozen=True)
class CategoryTrend:
    category_key: str
    window_start: date
    window_end: date
    recent_minor: int  # spend in the last 30 days (positive magnitude)
    usual_minor: int  # median of the three prior 30-day windows
    robust_z: float
    change_share: float  # (recent − usual) / usual
    count: int  # transactions in the recent window
    is_spike: bool


@dataclass(frozen=True)
class LongPayGap:
    from_payday: date
    to_payday: date
    days: int


def _window_total(rows: Sequence[tuple[date, int]], start: date, end: date) -> tuple[int, int]:
    picked = [amount for d, amount in rows if start <= d <= end]
    return sum(picked), len(picked)


def category_trends(
    txns: Sequence[Transaction],
    cats: Sequence[Categorisation],
    as_of: date,
    min_delta_minor: int = MIN_DELTA_MINOR,
) -> tuple[CategoryTrend, ...]:
    by_id = {c.transaction_id: c for c in cats}
    per_category: dict[str, list[tuple[date, int]]] = {}
    for t in txns:
        c = by_id.get(t.id)
        if c is None or t.amount_minor >= 0 or c.flow_kind not in _SPEND:
            continue
        per_category.setdefault(c.category_key, []).append((t.posted_on, -t.amount_minor))
    out = []
    for category, rows in per_category.items():
        end = as_of
        start = end - timedelta(days=WINDOW_DAYS - 1)
        recent, count = _window_total(rows, start, end)
        prior = []
        for k in range(1, 4):
            p_end = start - timedelta(days=1 + WINDOW_DAYS * (k - 1))
            p_start = p_end - timedelta(days=WINDOW_DAYS - 1)
            prior.append(_window_total(rows, p_start, p_end)[0])
        usual = int(statistics.median(prior))
        mad = statistics.median([abs(p - usual) for p in prior])
        z = (
            (recent - usual) / (1.4826 * mad + 1e-9)
            if mad
            else (float("inf") if recent > usual else 0.0)
        )
        delta = recent - usual
        share = delta / usual if usual else 0.0
        spike = z >= Z_THRESHOLD and abs(delta) >= max(min_delta_minor, MIN_DELTA_SHARE * usual)
        out.append(CategoryTrend(category, start, end, recent, usual, z, share, count, spike))
    return tuple(sorted(out, key=lambda t: -(t.recent_minor - t.usual_minor)))


def long_pay_gaps(paydays: Sequence[date]) -> tuple[LongPayGap, ...]:
    ordered = sorted(paydays)
    return tuple(
        LongPayGap(a, b, (b - a).days)
        for a, b in zip(ordered, ordered[1:], strict=False)
        if (b - a).days >= LONG_PAY_GAP_DAYS
    )
