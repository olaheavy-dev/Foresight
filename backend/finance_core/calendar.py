"""Business-day helpers driven by a holiday set (the locale pack names the calendar).

Pure date arithmetic. `holiday_set` turns a pack's holiday source into a frozenset of dates using
python-holidays; every other function takes that set, so the engine stays locale-free.
"""

from __future__ import annotations

import calendar as _cal
from collections.abc import Iterable
from datetime import date, timedelta

import holidays as _holidays

from backend.finance_core.types import PaydayRule


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


def payday_in_month(
    rule: PaydayRule, year: int, month: int, holidays: frozenset[date], shift_rule: str
) -> date | None:
    """The payday a monthly rule produces in a given month (None for non-monthly rules)."""
    if rule.kind == "last_working_day":
        return last_working_day(year, month, holidays)
    if rule.kind == "fixed_day" and rule.day_of_month is not None:
        day = rule.december_day if month == 12 and rule.december_day else rule.day_of_month
        return shift(clamp_day(year, month, day), shift_rule, holidays)
    return None


def paydays_between(
    rule: PaydayRule, start: date, end: date, holidays: frozenset[date], shift_rule: str
) -> list[date]:
    """All paydays a rule produces in [start, end]."""
    out: list[date] = []
    if rule.kind == "four_weekly" and rule.anchor_date is not None:
        d = rule.anchor_date
        while d > start:
            d -= timedelta(days=28)
        while d <= end:
            if d >= start:
                out.append(shift(d, shift_rule, holidays))
            d += timedelta(days=28)
        return out
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        pay = payday_in_month(rule, y, m, holidays, shift_rule)
        if pay is not None and start <= pay <= end:
            out.append(pay)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def next_payday(
    rule: PaydayRule, after: date, holidays: frozenset[date], shift_rule: str
) -> date | None:
    days = paydays_between(
        rule, after + timedelta(days=1), after + timedelta(days=62), holidays, shift_rule
    )
    return days[0] if days else None
