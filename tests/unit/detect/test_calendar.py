from __future__ import annotations

from datetime import date

from backend.finance_core.calendar import (
    holiday_set,
    last_working_day,
    next_working_day,
    paydays_between,
    previous_working_day,
)
from backend.finance_core.types import PaydayRule
from tests.unit.categorise.helpers import uk_pack

PACK = uk_pack()
HOLIDAYS = holiday_set(PACK.holiday_country, PACK.holiday_subdiv, range(2025, 2028))


def test_bank_holidays_loaded_from_pack_calendar() -> None:
    assert date(2026, 12, 25) in HOLIDAYS
    assert date(2026, 12, 28) in HOLIDAYS  # Boxing Day substitute (26th is a Saturday)


def test_weekend_shifts() -> None:
    assert previous_working_day(date(2026, 11, 28), HOLIDAYS) == date(2026, 11, 27)  # Sat → Fri
    assert next_working_day(date(2026, 11, 28), HOLIDAYS) == date(2026, 11, 30)  # Sat → Mon
    assert last_working_day(2026, 10, HOLIDAYS) == date(2026, 10, 30)


def test_fixed_day_payday_with_december_override() -> None:
    rule = PaydayRule(kind="fixed_day", day_of_month=28, december_day=18)
    days = paydays_between(rule, date(2026, 10, 12), date(2027, 3, 31), HOLIDAYS, PACK.payday_shift)
    assert days == [
        date(2026, 10, 28),
        date(2026, 11, 27),  # 28 Nov is a Saturday
        date(2026, 12, 18),  # early December pay
        date(2027, 1, 28),
        date(2027, 2, 26),  # 28 Feb is a Sunday
        date(2027, 3, 25),  # 28 Mar is a Sunday and Fri 26 Mar 2027 is Good Friday
    ]


def test_four_weekly_paydays() -> None:
    rule = PaydayRule(kind="four_weekly", anchor_date=date(2026, 10, 2))
    days = paydays_between(rule, date(2026, 10, 1), date(2026, 12, 31), HOLIDAYS, PACK.payday_shift)
    assert days == [date(2026, 10, 2), date(2026, 10, 30), date(2026, 11, 27), date(2026, 12, 24)]
