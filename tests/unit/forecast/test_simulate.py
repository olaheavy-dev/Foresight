"""E-SIM properties (docs/09 §8).

Determinism, zero scenario, linearity and income-delay conservation.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.finance_core.forecast.engine import balance_paths, prepare
from backend.finance_core.simulate import ScenarioError, _apply, simulate
from backend.finance_core.types import ForecastInputs, ScenarioModifier, ScenarioSpec
from tests.unit.forecast.conftest import make_inputs


def spec(*mods: ScenarioModifier, currency: str = "GBP") -> ScenarioSpec:
    return ScenarioSpec(name="test", currency=currency, modifiers=mods)


def holiday(on: date, amount: int = 120000) -> ScenarioModifier:
    return ScenarioModifier(type="one_off_outflow", date=on, amount_minor=amount, label="Holiday")


def test_sim1_determinism(inputs: ForecastInputs) -> None:
    s = spec(holiday(date(2026, 11, 6)))
    assert simulate(inputs, s) == simulate(inputs, s)


def test_sim2_zero_scenario_equals_baseline(inputs: ForecastInputs) -> None:
    res = simulate(inputs, spec())
    base, sim = res.baseline, res.simulated
    assert (sim.p10, sim.p50, sim.p90) == (base.p10, base.p50, base.p90)
    assert sim.pay_cycles == base.pay_cycles
    assert all(b == s for _d, b, s in res.delta_lows)


def test_sim3_one_off_outflow_is_linear(inputs: ForecastInputs) -> None:
    on, amount = date(2026, 11, 6), 120000
    prep = prepare(inputs)
    index = {d: i for i, d in enumerate(prep.dates)}
    base = balance_paths(prep, prep.flows)
    sim = balance_paths(prep, _apply(list(prep.flows), holiday(on, amount), prep, index))
    day = index[on]
    assert np.array_equal(base[:, :day], sim[:, :day])
    assert np.all(base[:, day:] - sim[:, day:] == amount)


def test_sim3_delta_lows_reflect_the_outflow(inputs: ForecastInputs) -> None:
    res = simulate(inputs, spec(holiday(date(2026, 11, 6))))
    by_payday = {d: (b, s) for d, b, s in res.delta_lows}
    b, s = by_payday[date(2026, 11, 27)]
    assert b - s == 120000


def test_sim6_income_delay_conservation(inputs: ForecastInputs) -> None:
    delay = ScenarioModifier(
        type="income_delay", income_stream_key="inc_salary", days=5, occurrences=1
    )
    prep = prepare(inputs)
    index = {d: i for i, d in enumerate(prep.dates)}
    base = balance_paths(prep, prep.flows)
    sim = balance_paths(prep, _apply(list(prep.flows), delay, prep, index))
    pay = index[date(2026, 10, 28)]
    new_pay = index[date(2026, 11, 2)]  # 28 Oct + 5 = Mon 2 Nov
    diff = base - sim
    assert np.all(diff[:, :pay] == 0)
    assert np.all(diff[:, pay:new_pay] == 405000)
    assert np.all(diff[:, new_pay:] == 0)


def test_income_delay_shifts_the_payday_in_results(inputs: ForecastInputs) -> None:
    delay = ScenarioModifier(
        type="income_delay", income_stream_key="inc_salary", days=5, occurrences=1
    )
    res = simulate(inputs, spec(delay))
    assert date(2026, 11, 2) in [c.payday for c in res.simulated.pay_cycles]
    assert date(2026, 10, 28) not in [c.payday for c in res.simulated.pay_cycles]


def test_cross_currency_scenario_is_rejected(inputs: ForecastInputs) -> None:
    with pytest.raises(ScenarioError, match="cross-currency"):
        simulate(inputs, spec(holiday(date(2026, 11, 6)), currency="EUR"))


@pytest.mark.parametrize(
    "mod",
    [
        ScenarioModifier(type="one_off_outflow", date=date(2026, 10, 1), amount_minor=100),
        ScenarioModifier(type="one_off_outflow", date=date(2026, 11, 6), amount_minor=-5),
        ScenarioModifier(type="income_delay", income_stream_key="nope", days=3),
        ScenarioModifier(type="category_cap"),
    ],
)
def test_invalid_scenarios_are_rejected_not_guessed(
    inputs: ForecastInputs, mod: ScenarioModifier
) -> None:
    with pytest.raises(ScenarioError):
        simulate(inputs, spec(mod))


@settings(max_examples=25, deadline=None)
@given(
    offset=st.integers(min_value=1, max_value=60),
    amount=st.integers(min_value=1, max_value=500_000),
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_property_outflow_never_raises_any_balance(offset: int, amount: int, seed: int) -> None:
    inputs = make_inputs(n_paths=20, horizon_days=60, seed=seed)
    on = inputs.as_of + timedelta(days=offset)
    res = simulate(inputs, spec(holiday(on, amount)))
    assert all(s <= b for b, s in zip(res.baseline.p50, res.simulated.p50, strict=True))
    assert res.simulated.min_balance_p50_minor <= res.baseline.min_balance_p50_minor


@settings(max_examples=15, deadline=None)
@given(seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_property_reproducible_for_any_seed(seed: int) -> None:
    inputs = dataclasses.replace(make_inputs(n_paths=20, horizon_days=45), seed=seed)
    s = spec(holiday(inputs.as_of + timedelta(days=10)))
    assert simulate(inputs, s) == simulate(inputs, s)
