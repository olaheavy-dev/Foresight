"""Income-stream detection (docs/07 §4.5, roadmap ENG-08).

Detected from ≥ 3 credits from the same payer with a regular cadence (gaps within tolerance) and
stable amounts (coefficient of variation ≤ 20 %, after dropping bonus/arrears one-offs above
`one_off_multiple` × median). Two observations are only a candidate. Payday rules are inferred
against the locale's working-day calendar; an early December credit is learned as an override.
Credits from income-like payers that never form a regular stream become an IRREGULAR stream with
their monthly totals as the distribution (freelance income).
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from backend.finance_core.calendar import last_working_day, payday_in_month
from backend.finance_core.types import (
    Cadence,
    Categorisation,
    FlowKind,
    IncomeStream,
    PaydayRule,
    Provenance,
    Transaction,
)

MIN_OCCURRENCES = 3
MAX_CV = 0.20
DIVERGENCE = 0.10


@dataclass(frozen=True)
class DivergenceFlag:
    stream_key: str
    declared_minor: int
    observed_minor: int


def _cadence(gaps: Sequence[int], days_of_month: Sequence[int]) -> Cadence | None:
    if not gaps:
        return None
    med = statistics.median(gaps)
    drifting = len(set(days_of_month)) > 2
    if 27 <= med <= 29 and len(gaps) >= 3 and drifting and all(26 <= g <= 30 for g in gaps):
        return Cadence.FOUR_WEEKLY
    if 26 <= med <= 34 and all(20 <= g <= 40 for g in gaps):
        return Cadence.MONTHLY
    if 6 <= med <= 8 and all(5 <= g <= 9 for g in gaps):
        return Cadence.WEEKLY
    return None


def _cv(values: Sequence[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    return statistics.pstdev(values) / mean if mean else 1.0


def infer_payday_rule(
    dates: Sequence[date], holidays: frozenset[date], shift_rule: str
) -> PaydayRule | None:
    """Pick the monthly rule that explains the most non-December paydays; learn a December override
    when December pay lands more than three days before the rule's date."""
    regular = [d for d in dates if d.month != 12] or list(dates)
    best: tuple[int, PaydayRule] | None = None
    candidates: list[PaydayRule] = [PaydayRule(kind="last_working_day")]
    candidates += [PaydayRule(kind="fixed_day", day_of_month=day) for day in range(1, 32)]
    for rule in candidates:
        hits = sum(
            payday_in_month(rule, d.year, d.month, holidays, shift_rule) == d for d in regular
        )
        # prefer fixed-day rules on ties: they also explain future months exactly
        if best is None or hits > best[0]:
            best = (hits, rule)
    if best is None or best[0] < max(2, int(0.75 * len(regular))):
        return None
    rule = best[1]
    for d in dates:
        if d.month != 12:
            continue
        expected = payday_in_month(rule, d.year, 12, holidays, shift_rule)
        if expected is not None and (expected - d).days > 3 and rule.kind == "fixed_day":
            rule = PaydayRule(kind="fixed_day", day_of_month=rule.day_of_month, december_day=d.day)
        elif expected is not None and (expected - d).days > 3:
            rule = PaydayRule(kind="last_working_day", december_day=d.day)
    return rule


def _income_candidates(
    txns: Iterable[Transaction], cats: dict[str, Categorisation]
) -> dict[str, list[Transaction]]:
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        c = cats.get(t.id)
        if t.amount_minor <= 0 or c is None or c.flow_kind != FlowKind.INCOME:
            continue
        if c.category_key in ("income.interest",):
            continue
        groups[t.counterparty or t.normalised].append(t)
    return groups


def detect_income_streams(
    txns: Sequence[Transaction],
    cats: Sequence[Categorisation],
    holidays: frozenset[date],
    shift_rule: str = "previous_working_day",
    one_off_multiple: float = 1.5,
) -> tuple[IncomeStream, ...]:
    by_id = {c.transaction_id: c for c in cats}
    streams: list[IncomeStream] = []
    irregular: list[Transaction] = []
    for source, rows in _income_candidates(txns, by_id).items():
        rows = sorted(rows, key=lambda t: t.posted_on)
        amounts = [t.amount_minor for t in rows]
        median = statistics.median(amounts)
        regular_rows = [t for t in rows if t.amount_minor <= one_off_multiple * median]
        if len(regular_rows) < MIN_OCCURRENCES:
            irregular.extend(rows)
            continue
        dates = [t.posted_on for t in regular_rows]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
        non_dec_gaps = [
            g
            for (a, b), g in zip(zip(dates, dates[1:], strict=False), gaps, strict=True)
            if a.month != 12 and b.month != 12
        ] or gaps
        cadence = _cadence(non_dec_gaps, [d.day for d in dates])
        reg_amounts = [t.amount_minor for t in regular_rows]
        if cadence is None or _cv(reg_amounts) > MAX_CV:
            irregular.extend(rows)
            continue
        rule: PaydayRule | None = None
        if cadence == Cadence.MONTHLY:
            rule = infer_payday_rule(dates, frozenset(holidays), shift_rule)
        elif cadence == Cadence.FOUR_WEEKLY:
            rule = PaydayRule(kind="four_weekly", anchor_date=dates[-1])
        streams.append(
            IncomeStream(
                key=f"inc_{_slug(source)}",
                source=source,
                amount_minor=int(statistics.median(reg_amounts)),
                currency=rows[0].currency,
                cadence=cadence,
                payday_rule=rule,
                provenance=Provenance.DETECTED,
                member_ids=tuple(t.id for t in regular_rows),
            )
        )
    if irregular:
        streams.append(_irregular_stream(irregular))
    return tuple(streams)


def _irregular_stream(rows: Sequence[Transaction]) -> IncomeStream:
    monthly: Counter[tuple[int, int]] = Counter()
    for t in rows:
        monthly[(t.posted_on.year, t.posted_on.month)] += t.amount_minor
    totals = tuple(monthly[k] for k in sorted(monthly))
    return IncomeStream(
        key="inc_irregular",
        source="Irregular income",
        amount_minor=int(statistics.median(totals)),
        currency=rows[0].currency,
        cadence=Cadence.IRREGULAR,
        payday_rule=None,
        provenance=Provenance.DETECTED,
        member_ids=tuple(t.id for t in rows),
        irregular_amounts_minor=totals,
    )


def divergence_flags(
    detected: Sequence[IncomeStream], declared: Sequence[IncomeStream]
) -> tuple[DivergenceFlag, ...]:
    """Declared figures that differ from what the data shows by more than 10 %."""
    flags = []
    for dec in declared:
        for det in detected:
            if det.source.upper() == dec.source.upper() and dec.amount_minor:
                if abs(det.amount_minor - dec.amount_minor) / dec.amount_minor > DIVERGENCE:
                    flags.append(DivergenceFlag(dec.key, dec.amount_minor, det.amount_minor))
    return tuple(flags)


def is_last_working_day(d: date, holidays: frozenset[date]) -> bool:
    return d == last_working_day(d.year, d.month, holidays)


def _slug(text: str) -> str:
    return "_".join(text.lower().split())[:40] or "unknown"
