from __future__ import annotations

from datetime import date

from backend.finance_core.calendar import (
    holiday_set,
    last_working_day,
    next_working_day,
    obligation_dates,
    paydays_between,
    previous_working_day,
)
from backend.finance_core.types import (
    Cadence,
    FlowKind,
    PaydayRule,
    RecurringObligation,
    WorkingDayShift,
)
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


def test_last_working_day_rule_honours_a_december_override() -> None:
    rule = PaydayRule(kind="last_working_day", december_day=18)
    days = paydays_between(rule, date(2026, 11, 1), date(2027, 1, 31), HOLIDAYS)
    assert days == [date(2026, 11, 30), date(2026, 12, 18), date(2027, 1, 29)]


def test_payday_shifted_back_into_the_previous_month_is_found() -> None:
    rule = PaydayRule(kind="fixed_day", day_of_month=1)
    # 1 Nov 2026 is a Sunday: pay moves back to Fri 30 Oct, which is inside an October range
    assert paydays_between(rule, date(2026, 10, 15), date(2026, 10, 31), HOLIDAYS) == [
        date(2026, 10, 30)
    ]


def test_obligation_dates_respect_active_months_and_weekdays() -> None:
    weekly = RecurringObligation(
        key="rob_gym",
        label="Gym",
        category_key="fitness",
        flow_kind=FlowKind.SPENDING,
        amount_minor=-1000,
        currency="GBP",
        cadence=Cadence.WEEKLY,
        anchor_day=0,
    )
    days = obligation_dates(weekly, date(2026, 10, 1), date(2026, 10, 31))
    assert days == [date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19), date(2026, 10, 26)]


def _monthly_bill(shift: WorkingDayShift) -> RecurringObligation:
    return RecurringObligation(
        key="rob_water",
        label="Water",
        category_key="utilities.water",
        flow_kind=FlowKind.SPENDING,
        amount_minor=-3000,
        currency="GBP",
        cadence=Cadence.MONTHLY,
        anchor_day=1,
        shift=shift,
    )


def test_obligation_shift_moves_weekend_dates() -> None:
    # Sat 1 Aug 2026: a direct debit is collected on Mon 3 Aug; a card payment stays on the 1st
    window = (date(2026, 7, 25), date(2026, 8, 10))
    assert obligation_dates(_monthly_bill(WorkingDayShift.NEXT), *window, HOLIDAYS) == [
        date(2026, 8, 3)
    ]
    assert obligation_dates(_monthly_bill(WorkingDayShift.NONE), *window, HOLIDAYS) == [
        date(2026, 8, 1)
    ]


def test_shifted_obligation_from_before_the_window_lands_inside_it() -> None:
    days = obligation_dates(
        _monthly_bill(WorkingDayShift.NEXT), date(2026, 8, 2), date(2026, 8, 10), HOLIDAYS
    )
    assert days == [date(2026, 8, 3)]


def test_learned_payday_shift_overrides_the_pack_default() -> None:
    rule = PaydayRule(kind="fixed_day", day_of_month=28, shift=WorkingDayShift.NEXT)
    # Sat 28 Nov 2026 → Mon 30 Nov, although the uk pack's default moves pay earlier
    assert paydays_between(
        rule, date(2026, 11, 1), date(2026, 11, 30), HOLIDAYS, PACK.payday_shift
    ) == [date(2026, 11, 30)]
