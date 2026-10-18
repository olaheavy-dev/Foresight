"""Behaviour trends: category spikes and long pay gaps (docs/07 §6.6).

A category spike compares the last 30 days with the median of up to six prior 30-day windows
(as many full windows as the ledger's history covers, never fewer than three):
robust z ≥ 2.0 and |change| ≥ max(£25, 15 % of the usual amount) (docs/00 §13). Only real
behaviour is compared: spending, fees and betting, without one-offs and without the
`uncategorised` bucket, which mixes unrelated merchants. A one-off is a row ≥ 3× its category's
median over the windows that is also rare there (at most two such rows per four windows, i.e.
large amounts don't recur, docs/00 §13); in a category where large amounts are routine
(restaurant meals among coffees) they are ordinary behaviour and stay in. A category with no
spending in the prior windows has no baseline to compare against; a first purchase is a
new-merchant finding, not a trend.

A category must also be a regular behaviour: at least MIN_BASE_COUNT purchases in a typical prior
window (the median of the prior windows). Below that, a month's total is a handful of purchases
and a "spike" is one or two extra ones (a second taxi, a dentist visit), not a change in behaviour
(docs/07 §6.6, measured on dev windows; owner-approved 13 Oct 2026).

Six prior windows rather than three (owner-approved 14 Oct 2026): the median and MAD of three
months swing with one busy month, which made ordinary variation look like a spike (clean
persona-months: 0.67 false spikes each with three windows, 0.25 with six).
"""

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
ONE_OFF_MULTIPLE = 3
ONE_OFF_MAX_ROWS = 2  # more large rows than this per four windows ⇒ large amounts recur
MIN_PRIOR_WINDOWS = 3
MAX_PRIOR_WINDOWS = 6
NOT_A_BEHAVIOUR = frozenset({"uncategorised"})
MIN_BASE_COUNT = 5  # median purchases per prior window for a category to count as a behaviour


@dataclass(frozen=True)
class CategoryTrend:
    category_key: str
    window_start: date
    window_end: date
    recent_minor: int  # spend in the last 30 days (positive magnitude)
    usual_minor: int  # median of the prior 30-day windows
    robust_z: float
    change_share: float  # (recent − usual) / usual
    count: int  # transactions in the recent window
    is_spike: bool
    # The rows counted in the recent window (refunds, non-spending and rare one-offs excluded),
    # so the evidence chain shows exactly these, never a looser re-query (#62 review).
    recent_ids: tuple[str, ...] = ()


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
    earliest = min((t.posted_on for t in txns), default=as_of)
    covered = ((as_of - earliest).days + 1) // WINDOW_DAYS - 1  # full windows before the recent one
    n_prior = max(MIN_PRIOR_WINDOWS, min(MAX_PRIOR_WINDOWS, covered))
    max_large = ONE_OFF_MAX_ROWS * (n_prior + 1) // 4
    first = as_of - timedelta(days=(n_prior + 1) * WINDOW_DAYS - 1)
    per_category: dict[str, list[tuple[date, int, str]]] = {}
    for t in txns:
        c = by_id.get(t.id)
        if c is None or t.amount_minor >= 0 or c.flow_kind not in _SPEND:
            continue
        if c.category_key in NOT_A_BEHAVIOUR or not first <= t.posted_on <= as_of:
            continue
        per_category.setdefault(c.category_key, []).append((t.posted_on, -t.amount_minor, t.id))
    out = []
    for category, all_rows in per_category.items():
        large = ONE_OFF_MULTIPLE * statistics.median(a for _d, a, _i in all_rows)
        rare = sum(1 for _d, a, _i in all_rows if a >= large) <= max_large
        kept = [(d, a, i) for d, a, i in all_rows if not (rare and a >= large)]
        rows = [(d, a) for d, a, _i in kept]
        end = as_of
        start = end - timedelta(days=WINDOW_DAYS - 1)
        recent, count = _window_total(rows, start, end)
        recent_ids = tuple(sorted(i for d, _a, i in kept if start <= d <= end))
        prior = []
        prior_counts = []
        for k in range(1, n_prior + 1):
            p_end = start - timedelta(days=1 + WINDOW_DAYS * (k - 1))
            p_start = p_end - timedelta(days=WINDOW_DAYS - 1)
            p_total, p_count = _window_total(rows, p_start, p_end)
            prior.append(p_total)
            prior_counts.append(p_count)
        usual = int(statistics.median(prior))
        mad = statistics.median([abs(p - usual) for p in prior])
        z = (
            (recent - usual) / (1.4826 * mad + 1e-9)
            if mad
            else (float("inf") if recent > usual else 0.0)
        )
        delta = recent - usual
        share = delta / usual if usual else 0.0
        regular = statistics.median(prior_counts) >= MIN_BASE_COUNT
        spike = (
            usual > 0
            and regular
            and z >= Z_THRESHOLD
            and abs(delta) >= max(min_delta_minor, MIN_DELTA_SHARE * usual)
        )
        out.append(
            CategoryTrend(category, start, end, recent, usual, z, share, count, spike, recent_ids)
        )
    return tuple(sorted(out, key=lambda t: -(t.recent_minor - t.usual_minor)))


def long_pay_gaps(paydays: Sequence[date]) -> tuple[LongPayGap, ...]:
    ordered = sorted(paydays)
    return tuple(
        LongPayGap(a, b, (b - a).days)
        for a, b in zip(ordered, ordered[1:], strict=False)
        if (b - a).days >= LONG_PAY_GAP_DAYS
    )
