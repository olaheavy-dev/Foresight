"""Business-day and schedule helpers driven by a holiday set (the locale pack names the calendar).

Pure date arithmetic. `holiday_set` turns a pack's holiday source into a frozenset of dates using
python-holidays; every other function takes that set, so the engine stays locale-free. Income
paydays and recurring-obligation dates are expanded here for the detectors, the forecast engine
and the simulator alike, so they can never disagree about when money moves.
"""

from __future__ import annotations

import calendar as _cal
from collections.abc import Iterable, Iterator
from datetime import date, timedelta

import holidays as _holidays

from backend.finance_core.types import Cadence, PaydayRule, RecurringObligation

DEFAULT_SHIFT = "previous_working_day"


def holiday_set(country: str, subdiv: str | None, years: Iterable[int]) -> frozenset[date]:
    days = _holidays.country_holidays(country, subdiv=subdiv, years=list(years))
    return frozenset(days.keys())


def is_working_day(d: date, holidays: frozenset[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def previous_working_day(d: date, holidays: frozenset[date]) -> date:
    """`d` itself if it is a working day, else the closest earlier working day."""
    while not is_working_day(d, holidays):
        d -= timedelta(days=1)
    return d


def next_working_day(d: date, holidays: frozenset[date]) -> date:
    """`d` itself if it is a working day, else the closest later working day."""
    while not is_working_day(d, holidays):
        d += timedelta(days=1)
    return d


def last_working_day(year: int, month: int, holidays: frozenset[date]) -> date:
    return previous_working_day(date(year, month, _cal.monthrange(year, month)[1]), holidays)


def shift(d: date, rule: str, holidays: frozenset[date]) -> date:
    """Apply a pack's weekend/holiday shift rule ("previous_working_day" | "next_working_day")."""
    if rule == "next_working_day":
        return next_working_day(d, holidays)
    return previous_working_day(d, holidays)


def clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, _cal.monthrange(year, month)[1]))


def _months(start: date, end: date) -> Iterator[tuple[int, int]]:
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def payday_in_month(
    rule: PaydayRule, year: int, month: int, holidays: frozenset[date], shift_rule: str
) -> date | None:
    """The payday a monthly rule produces for a given month (None for non-monthly rules).

    A December override (early Christmas pay) applies to both monthly kinds. The result can fall
    in the previous month when the nominal day is shifted back across a month boundary.
    """
    if rule.kind not in ("last_working_day", "fixed_day"):
        return None
    if month == 12 and rule.december_day is not None:
        return shift(clamp_day(year, month, rule.december_day), shift_rule, holidays)
    if rule.kind == "last_working_day":
        return last_working_day(year, month, holidays)
    if rule.day_of_month is None:
        return None
    return shift(clamp_day(year, month, rule.day_of_month), shift_rule, holidays)


def paydays_between(
    rule: PaydayRule,
    start: date,
    end: date,
    holidays: frozenset[date],
    shift_rule: str = DEFAULT_SHIFT,
) -> list[date]:
    """All paydays a rule produces in [start, end], after the shift rule is applied."""
    out: set[date] = set()
    if rule.kind == "four_weekly":
        if rule.anchor_date is None:
            return []
        step = timedelta(days=28)
        d = rule.anchor_date
        while d > start - step:
            d -= step
        while d <= end + step:
            pay = shift(d, shift_rule, holidays)
            if start <= pay <= end:
                out.add(pay)
            d += step
        return sorted(out)
    # a month either side: a shifted payday can cross a month boundary
    for y, m in _months(start - timedelta(days=31), end + timedelta(days=31)):
        monthly = payday_in_month(rule, y, m, holidays, shift_rule)
        if monthly is not None and start <= monthly <= end:
            out.add(monthly)
    return sorted(out)


def next_payday(
    rule: PaydayRule, after: date, holidays: frozenset[date], shift_rule: str = DEFAULT_SHIFT
) -> date | None:
    days = paydays_between(
        rule, after + timedelta(days=1), after + timedelta(days=62), holidays, shift_rule
    )
    return days[0] if days else None


def obligation_dates(ob: RecurringObligation, start: date, end: date) -> list[date]:
    """Occurrences of a recurring obligation in [start, end].

    MONTHLY/QUARTERLY/ANNUAL use anchor_day (day of month) restricted to active_months (so
    council tax Apr–Jan never falls in Feb–Mar, and an annual bill lists its single month).
    WEEKLY uses anchor_day as a weekday (0 = Monday). Direct debits and standing orders are not
    moved for weekends here: banks collect them on the next working day, which the statement
    shows, and the detector learns the observed day. FOUR_WEEKLY and IRREGULAR obligations need an
    anchor date the type does not carry; the recurring detector does not emit them yet, so they
    are not projected.
    """
    out: list[date] = []
    if ob.anchor_day is None:
        return out
    if ob.cadence in (Cadence.MONTHLY, Cadence.QUARTERLY, Cadence.ANNUAL):
        for y, m in _months(start, end):
            if m not in ob.active_months:
                continue
            d = clamp_day(y, m, ob.anchor_day)
            if start <= d <= end:
                out.append(d)
    elif ob.cadence is Cadence.WEEKLY:
        d = start
        while d <= end:
            if d.weekday() == ob.anchor_day % 7 and d.month in ob.active_months:
                out.append(d)
            d += timedelta(days=1)
    return out
