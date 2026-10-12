from __future__ import annotations

import dataclasses
import time
from datetime import date

import numpy as np

from backend.finance_core.calc import content_hash
from backend.finance_core.forecast._calendar import obligation_dates, paydays
from backend.finance_core.forecast.engine import balance_paths, build_forecast, prepare
from backend.finance_core.types import ForecastInputs, PaydayRule
from tests.unit.forecast.conftest import EW_HOLIDAYS, make_inputs


def test_same_inputs_give_identical_results(inputs: ForecastInputs) -> None:
    a, b = build_forecast(inputs), build_forecast(inputs)
    assert a == b
    assert a.inputs_hash == content_hash(inputs)


def test_different_seed_changes_draws_but_not_hash_semantics(inputs: ForecastInputs) -> None:
    other = dataclasses.replace(inputs, seed=7)
    assert build_forecast(other).inputs_hash != build_forecast(inputs).inputs_hash


def test_quantiles_are_ordered_and_start_at_the_balance(inputs: ForecastInputs) -> None:
    fc = build_forecast(inputs)
    assert fc.p10[0] == fc.p50[0] == fc.p90[0] == inputs.starting_balance_minor
    assert all(lo <= mid <= hi for lo, mid, hi in zip(fc.p10, fc.p50, fc.p90, strict=True))
    assert len(fc.dates) == inputs.horizon_days + 1


def test_pay_cycles_and_buffer_chance(inputs: ForecastInputs) -> None:
    fc = build_forecast(inputs)
    paydays_ = [c.payday for c in fc.pay_cycles]
    assert paydays_[0] == date(2026, 10, 28)
    assert date(2026, 12, 18) in paydays_  # December override (early pay)
    first = fc.pay_cycles[0]
    assert first.low.p10 <= first.low.p50 <= first.low.p90
    assert first.chance_below_buffer is not None
    assert 0.0 <= first.chance_below_buffer <= 1.0
    assert date(2026, 10, 13) <= first.low_date < date(2026, 10, 28)


def test_relative_mode_has_no_breach_probability(inputs: ForecastInputs) -> None:
    fc = build_forecast(dataclasses.replace(inputs, starting_balance_provenance="relative"))
    assert fc.p50[0] == 0
    assert fc.buffer_minor is None
    assert all(c.chance_below_buffer is None for c in fc.pay_cycles)


def test_no_history_is_deterministic_calendar(inputs: ForecastInputs) -> None:
    fc = build_forecast(dataclasses.replace(inputs, discretionary_history=()))
    assert fc.p10 == fc.p50 == fc.p90


def test_discretionary_draws_come_from_history(inputs: ForecastInputs) -> None:
    prep = prepare(inputs)
    observed = {a for (_d, _c, a) in inputs.discretionary_history}
    assert prep.discretionary[:, 0].sum() == 0
    assert prep.discretionary.max() <= 0
    assert prep.discretionary.min() >= sum(sorted(observed)[:3])  # at most one day's spend


def test_payday_on_saturday_moves_to_friday() -> None:
    rule = PaydayRule(kind="fixed_day", day_of_month=28)
    days = paydays(rule, date(2026, 11, 1), date(2026, 11, 30), EW_HOLIDAYS)
    assert days == [date(2026, 11, 27)]  # 28 Nov 2026 is a Saturday


def test_last_working_day_and_bank_holiday() -> None:
    rule = PaydayRule(kind="last_working_day")
    days = paydays(rule, date(2027, 5, 1), date(2027, 5, 31), EW_HOLIDAYS)
    assert days == [date(2027, 5, 28)]  # 31 May 2027 is the Spring bank holiday


def test_council_tax_skips_february_and_march(inputs: ForecastInputs) -> None:
    ctax = next(o for o in inputs.obligations if o.key == "rob_ctax")
    months = {d.month for d in obligation_dates(ctax, date(2027, 1, 1), date(2027, 4, 30))}
    assert months == {1, 4}


def test_known_one_off_lowers_every_path_from_its_date(inputs: ForecastInputs) -> None:
    without = dataclasses.replace(inputs, known_flows=())
    prep_a, prep_b = prepare(inputs), prepare(without)
    a = balance_paths(prep_a, prep_a.flows)
    b = balance_paths(prep_b, prep_b.flows)
    day = prep_a.dates.index(date(2026, 10, 14))
    assert np.array_equal(a[:, :day], b[:, :day])
    assert np.all(b[:, day:] - a[:, day:] == 65000)


def test_ninety_day_forecast_with_500_paths_is_fast() -> None:
    inputs = make_inputs(n_paths=500, horizon_days=90)
    start = time.perf_counter()
    build_forecast(inputs)
    assert time.perf_counter() - start < 3.0
