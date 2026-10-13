from __future__ import annotations

from datetime import date, timedelta

from backend.finance_core.calendar import holiday_set, payday_in_month
from backend.finance_core.categorise.rules import categorise
from backend.finance_core.detect.income import detect_income_streams, divergence_flags
from backend.finance_core.types import (
    Cadence,
    Categorisation,
    CategorisationMethod,
    FlowKind,
    IncomeStream,
    PaydayRule,
    Provenance,
)
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


def test_irregular_income_is_one_total_per_covered_month_with_zero_months() -> None:
    # credits in Jan, Feb, Apr and May; the ledger runs from 31 Dec to 30 Jun, so Jan–Jun are
    # fully covered and March and June count as months with no irregular income
    amounts = {1: 90000, 2: 650000, 4: 210000, 5: 480000}
    rows = [
        txn("CLIENT CO LTD", a, on=date(2026, m, 10), bank_type="BACS") for m, a in amounts.items()
    ]
    rows += [
        txn("TESCO STORES", -1000, on=date(2025, 12, 31)),
        txn("TESCO STORES", -1000, on=date(2026, 6, 30)),
    ]
    (stream,) = [s for s in _detect(rows) if s.cadence == Cadence.IRREGULAR]
    assert stream.irregular_amounts_minor == (90000, 650000, 0, 210000, 480000, 0)


def test_split_salary_parts_on_the_same_day_are_summed() -> None:
    rows = []
    for row in _salary_rows(MONTHS, early_december=None):
        rows.append(txn("ACME ANALYTICS LTD", 283500, on=row.posted_on, bank_type="BACS"))
        rows.append(txn("ACME ANALYTICS LTD", 121500, on=row.posted_on, bank_type="BACS"))
    (stream,) = _detect(rows)
    assert stream.cadence == Cadence.MONTHLY
    assert stream.amount_minor == SALARY
    assert len(stream.member_ids) == 2 * len(MONTHS)


def test_arrears_paid_with_salary_do_not_break_the_stream() -> None:
    rows = _salary_rows(MONTHS)
    payday = rows[4].posted_on
    rows.append(txn("ACME ANALYTICS LTD", 22000, on=payday, bank_type="BACS"))  # arrears
    rows.append(txn("ACME ANALYTICS LTD", 150000, on=rows[7].posted_on, bank_type="BACS"))  # bonus
    (stream,) = [s for s in _detect(rows) if s.cadence != Cadence.IRREGULAR]
    assert stream.cadence == Cadence.MONTHLY
    assert stream.amount_minor == SALARY
    assert len(stream.member_ids) == len(MONTHS)


def test_confirmed_payers_count_as_income() -> None:
    amounts = [90000, 480000, 150000, 610000, 220000]  # a freelancer's client: varied invoices
    rows = [txn("BRIGHTWATER MEDIA", a, on=date(2026, k + 1, 12)) for k, a in enumerate(amounts)]
    cats = [
        Categorisation(
            r.id, "inflow_unconfirmed", FlowKind.INFLOW_UNCONFIRMED, CategorisationMethod.RULE, 0.9
        )
        for r in rows
    ]
    assert detect_income_streams(rows, cats, HOLIDAYS) == ()
    source = rows[0].counterparty or rows[0].normalised
    (stream,) = detect_income_streams(rows, cats, HOLIDAYS, confirmed_sources=[source])
    assert stream.cadence == Cadence.IRREGULAR
    assert sum(stream.irregular_amounts_minor) > 0


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
