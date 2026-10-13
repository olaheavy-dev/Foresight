"""UK calendar rules used by the generator (England & Wales bank holidays)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from functools import lru_cache

import holidays


@lru_cache(maxsize=1)
def _bank_holidays() -> frozenset[date]:
    cal = holidays.country_holidays("GB", subdiv="ENG", years=range(2023, 2029))
    return frozenset(cal.keys())


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _bank_holidays()


def previous_working_day(d: date) -> date:
    while not is_working_day(d):
        d -= timedelta(days=1)
    return d


def next_working_day(d: date) -> date:
    while not is_working_day(d):
        d += timedelta(days=1)
    return d


def months_between(start: date, end: date) -> Iterator[tuple[int, int]]:
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fixed_day_payday(year: int, month: int, day: int, december_day: int | None) -> date:
    """Pay on `day`, moved to the previous working day; December may be paid early."""
    if month == 12 and december_day is not None:
        return previous_working_day(date(year, 12, december_day))
    return previous_working_day(date(year, month, day))


def four_weekly_paydays(anchor: date, start: date, end: date) -> list[date]:
    out = []
    d = anchor
    while d > start:
        d -= timedelta(days=28)
    while d <= end:
        if d >= start:
            out.append(previous_working_day(d))
        d += timedelta(days=28)
    return out


def collection_date(year: int, month: int, day: int) -> date:
    """Direct debits and standing orders: the next working day when the date isn't one."""
    return next_working_day(date(year, month, day))
