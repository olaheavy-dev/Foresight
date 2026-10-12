"""Private calendar helpers for the forecast engine.

The engine is locale-free: holidays arrive in ForecastInputs from the workspace's locale pack.
This module only expands income and obligation schedules into dates. (A shared calendar module
may supersede these helpers; they are kept private to the forecast package.)
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from datetime import date, timedelta

from backend.finance_core.types import Cadence, PaydayRule, RecurringObligation


def is_working_day(d: date, holidays: frozenset[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def previous_working_day(d: date, holidays: frozenset[date]) -> date:
    while not is_working_day(d, holidays):
        d -= timedelta(days=1)
    return d


def next_working_day(d: date, holidays: frozenset[date]) -> date:
    while not is_working_day(d, holidays):
        d += timedelta(days=1)
    return d


def _months(start: date, end: date) -> Iterator[tuple[int, int]]:
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _clamped(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def paydays(rule: PaydayRule, start: date, end: date, holidays: frozenset[date]) -> list[date]:
    """All paydays in [start, end] for a rule; fixed dates move to the previous working day."""
    out: list[date] = []
    if rule.kind == "four_weekly":
        if rule.anchor_date is None:
            return out
        step = timedelta(days=28)
        d = rule.anchor_date
        while d > start:
            d -= step
        while d <= end:
            pd = previous_working_day(d, holidays)
            if start <= pd <= end:
                out.append(pd)
            d += step
        return out
    for y, m in _months(start - timedelta(days=31), end + timedelta(days=31)):
        if m == 12 and rule.december_day is not None:
            nominal = _clamped(y, m, rule.december_day)
        elif rule.kind == "last_working_day":
            nominal = date(y, m, calendar.monthrange(y, m)[1])
        elif rule.kind == "fixed_day" and rule.day_of_month is not None:
            nominal = _clamped(y, m, rule.day_of_month)
        else:
            continue
        pd = previous_working_day(nominal, holidays)
        if start <= pd <= end:
            out.append(pd)
    return sorted(set(out))


def obligation_dates(ob: RecurringObligation, start: date, end: date) -> list[date]:
    """Occurrences of a recurring obligation in [start, end].

    MONTHLY/QUARTERLY/ANNUAL use anchor_day (day of month) restricted to active_months (so
    council tax Apr–Jan never falls in Feb–Mar, and an annual bill lists its single month).
    WEEKLY uses anchor_day as a weekday (0 = Monday). FOUR_WEEKLY and IRREGULAR obligations
    need an anchor date the type does not carry, so they are not projected in v1.
    """
    out: list[date] = []
    if ob.anchor_day is None:
        return out
    if ob.cadence in (Cadence.MONTHLY, Cadence.QUARTERLY, Cadence.ANNUAL):
        for y, m in _months(start, end):
            if m not in ob.active_months:
                continue
            d = _clamped(y, m, ob.anchor_day)
            if start <= d <= end:
                out.append(d)
    elif ob.cadence is Cadence.WEEKLY:
        d = start
        while d <= end:
            if d.weekday() == ob.anchor_day % 7 and d.month in ob.active_months:
                out.append(d)
            d += timedelta(days=1)
    return out
