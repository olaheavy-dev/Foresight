from __future__ import annotations

from datetime import date, timedelta

from backend.finance_core.calendar import holiday_set, payday_in_month
from backend.finance_core.categorise.rules import categorise
from backend.finance_core.detect.income import detect_income_streams, divergence_flags
from backend.finance_core.types import Cadence, IncomeStream, PaydayRule, Provenance
from tests.unit.categorise.helpers import txn, uk_pack

PACK = uk_pack()
HOLIDAYS = holiday_set(PACK.holiday_country, PACK.holiday_subdiv, range(2025, 2028))
SALARY = 405000


def _salary_rows(months: list[tuple[int, int]], early_december: int | None = 18):  # type: ignore[no-untyped-def]
    rule = PaydayRule(kind="fixed_day", day_of_month=28)
    rows = []
    for y, m in months:
        on = payday_in_month(rule, y, m, HOLIDAYS, PACK.payday_shift)
        assert on is not None
        if m == 12 and early_december:
            on = date(y, 12, early_december)
        rows.append(txn("ACME ANALYTICS LTD", SALARY, on=on, bank_type="Bacs (Direct Credit)"))
    return rows


MONTHS = [(2025, m) for m in range(10, 13)] + [(2026, m) for m in range(1, 10)]


def _detect(rows):  # type: ignore[no-untyped-def]
    cats = [categorise(r, PACK) for r in rows]
    return detect_income_streams(rows, cats, HOLIDAYS, PACK.payday_shift, PACK.one_off_multiple)


def test_salary_amount_and_payday_rule() -> None:
    (stream,) = _detect(_salary_rows(MONTHS))
    assert stream.cadence == Cadence.MONTHLY
    assert stream.amount_minor == SALARY  # INC-2: within ±2 % (exact here)
    assert stream.payday_rule == PaydayRule(kind="fixed_day", day_of_month=28, december_day=18)
    assert stream.provenance == Provenance.DETECTED


def test_bonus_is_excluded_as_one_off() -> None:
    rows = _salary_rows(MONTHS)
    rows.append(txn("ACME ANALYTICS LTD", SALARY * 2, on=date(2026, 3, 31), bank_type="BACS"))
    (stream,) = [s for s in _detect(rows) if s.cadence != Cadence.IRREGULAR]
    assert stream.amount_minor == SALARY
    assert len(stream.member_ids) == len(MONTHS)


def test_two_paydays_are_not_a_stream() -> None:
    streams = _detect(_salary_rows([(2026, 8), (2026, 9)]))
    assert all(s.cadence == Cadence.IRREGULAR for s in streams)


def test_four_weekly_pay() -> None:
    start = date(2026, 1, 2)
    rows = [
        txn("ACME ANALYTICS LTD", 300000, on=start + timedelta(days=28 * k), bank_type="BACS")
        for k in range(8)
    ]
    (stream,) = _detect(rows)
    assert stream.cadence == Cadence.FOUR_WEEKLY
    assert stream.payday_rule is not None
    assert stream.payday_rule.kind == "four_weekly"


def test_irregular_freelance_income_becomes_a_distribution() -> None:
    amounts = [90000, 650000, 210000, 120000, 480000, 95000]
    rows = [
        txn("CLIENT CO LTD", a, on=date(2026, k + 1, 3 + 5 * k), bank_type="BACS")
        for k, a in enumerate(amounts)
    ]
    (stream,) = _detect(rows)
    assert stream.cadence == Cadence.IRREGULAR
    assert sorted(stream.irregular_amounts_minor) == sorted(amounts)


def test_declared_income_divergence_flag() -> None:
    (detected,) = _detect(_salary_rows(MONTHS))
    declared = IncomeStream(
        key="inc_declared",
        source=detected.source,
        amount_minor=350000,
        currency="GBP",
        cadence=Cadence.MONTHLY,
        payday_rule=None,
        provenance=Provenance.DECLARED,
    )
    (flag,) = divergence_flags([detected], [declared])
    assert flag.observed_minor == SALARY
