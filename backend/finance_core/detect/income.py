"""Income-stream detection (docs/07 §4.5, roadmap ENG-08).

Detected from ≥ 3 credits from the same payer with a regular cadence (gaps within tolerance) and
stable amounts (coefficient of variation ≤ 20 %, after dropping bonus/arrears one-offs above
`one_off_multiple` × median). Two observations are only a candidate. Payday rules are inferred
against the locale's working-day calendar; an early December credit is learned as an override.
Credits from income-like payers that never form a regular stream become an IRREGULAR stream with
their monthly totals as the distribution (freelance income): one total per calendar month the
ledger fully covers (up to the last 12), months with no such credit counting as zero, which is
what the forecast engine draws from (docs/07 §4.5).

Several credits from one payer on the same payday are one payday: when that happens on most
paydays the parts are summed (a salary paid in two transfers); otherwise the credit nearest the
usual amount is the pay and the others (arrears, a bonus) are one-offs that are not projected.
"""

from __future__ import annotations

import calendar
import statistics
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Sequence
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
IRREGULAR_MONTHS = 12
SPLIT_SHARE = 0.75  # same-day parts on ≥ 75 % of paydays ⇒ the pay is split, so sum the parts


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
    txns: Iterable[Transaction],
    cats: dict[str, Categorisation],
    confirmed_sources: Collection[str] = (),
) -> dict[str, list[Transaction]]:
    groups: dict[str, list[Transaction]] = defaultdict(list)
    confirmed = {s.upper() for s in confirmed_sources}
    for t in txns:
        c = cats.get(t.id)
        if t.amount_minor <= 0 or c is None:
            continue
        user_confirmed = (
            c.flow_kind == FlowKind.INFLOW_UNCONFIRMED
            and (t.counterparty or t.normalised).upper() in confirmed
        )
        if c.flow_kind != FlowKind.INCOME and not user_confirmed:
            continue
        if c.category_key in ("income.interest",):
            continue
        groups[t.counterparty or t.normalised].append(t)
    return groups


def _paydays(rows: Sequence[Transaction]) -> list[tuple[date, list[Transaction], int]]:
    """Group a payer's credits by day and pick each day's pay: the sum of the parts when most
    days have several parts (split pay), else the credit nearest the payer's median amount.
    Returns (day, credits that make up the pay, pay amount) per day."""
    by_day: dict[date, list[Transaction]] = defaultdict(list)
    for t in rows:
        by_day[t.posted_on].append(t)
    days = sorted(by_day)
    multi = sum(1 for d in days if len(by_day[d]) > 1)
    if days and multi >= SPLIT_SHARE * len(days) and multi > 0:
        return [(d, by_day[d], sum(t.amount_minor for t in by_day[d])) for d in days]
    median = statistics.median(t.amount_minor for t in rows)
    out = []
    for d in days:
        pay = min(by_day[d], key=lambda t: (abs(t.amount_minor - median), t.id))
        out.append((d, [pay], pay.amount_minor))
    return out


def detect_income_streams(
    txns: Sequence[Transaction],
    cats: Sequence[Categorisation],
    holidays: frozenset[date],
    shift_rule: str = "previous_working_day",
    one_off_multiple: float = 1.5,
    confirmed_sources: Collection[str] = (),
) -> tuple[IncomeStream, ...]:
    """Income streams in a ledger. `confirmed_sources` are counterparties the user has said pay
    them income (docs/00 §6a "Check what we found"); their otherwise-unconfirmed credits count as
    income from then on, so a freelancer's clients become an irregular stream."""
    by_id = {c.transaction_id: c for c in cats}
    streams: list[IncomeStream] = []
    irregular: list[Transaction] = []
    for source, rows in _income_candidates(txns, by_id, confirmed_sources).items():
        rows = sorted(rows, key=lambda t: (t.posted_on, t.id))
        pays = _paydays(rows)
        median = statistics.median(amount for _d, _parts, amount in pays)
        regular = [p for p in pays if p[2] <= one_off_multiple * median]
        if len(regular) < MIN_OCCURRENCES:
            irregular.extend(rows)
            continue
        regular_rows = [t for _d, parts, _a in regular for t in parts]
        dates = [d for d, _parts, _a in regular]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
        non_dec_gaps = [
            g
            for (a, b), g in zip(zip(dates, dates[1:], strict=False), gaps, strict=True)
            if a.month != 12 and b.month != 12
        ] or gaps
        cadence = _cadence(non_dec_gaps, [d.day for d in dates])
        reg_amounts = [a for _d, _parts, a in regular]
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
        first = min(t.posted_on for t in txns)
        last = max(t.posted_on for t in txns)
        streams.append(_irregular_stream(irregular, first, last))
    return tuple(streams)


def _full_months(first: date, last: date) -> list[tuple[int, int]]:
    """Calendar months the ledger covers completely (first day through last day)."""
    y, m = (first.year, first.month) if first.day == 1 else _next_month(first.year, first.month)
    out: list[tuple[int, int]] = []
    while True:
        month_end = date(y, m, calendar.monthrange(y, m)[1])
        if month_end > last:
            return out
        out.append((y, m))
        y, m = _next_month(y, m)


def _next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _irregular_stream(rows: Sequence[Transaction], first: date, last: date) -> IncomeStream:
    monthly: Counter[tuple[int, int]] = Counter()
    for t in rows:
        monthly[(t.posted_on.year, t.posted_on.month)] += t.amount_minor
    months = _full_months(first, last)[-IRREGULAR_MONTHS:]
    # zero months count: a month with no irregular credit is a real outcome, not missing data
    totals = tuple(monthly[k] for k in months) or tuple(monthly[k] for k in sorted(monthly))
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
