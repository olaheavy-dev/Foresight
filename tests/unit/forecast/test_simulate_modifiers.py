"""The scenario modifiers beyond v1 (docs/07 §6.5): each changes exactly what it says, on the same
draws as the baseline."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import pytest

from backend.finance_core.simulate import ScenarioError, simulate
from backend.finance_core.types import ScenarioModifier, ScenarioSpec
from evals.common import build_ledger, load_dataset
from evals.suites.forecast import inputs_at


@pytest.fixture(scope="module")
def base():  # type: ignore[no-untyped-def]
    ds = load_dataset("P1-base")
    inputs = inputs_at(ds, build_ledger(ds), str(ds.accounts[0]["id"]), ds.as_of)
    return dataclasses.replace(inputs, n_paths=100, horizon_days=120)


def _sim(base, *mods: ScenarioModifier):  # type: ignore[no-untyped-def]
    return simulate(base, ScenarioSpec("t", base.currency, tuple(mods)))


def _end_shift(base, *mods: ScenarioModifier) -> int:  # type: ignore[no-untyped-def]
    res = _sim(base, *mods)
    return res.simulated.p50[-1] - res.baseline.p50[-1]


def test_split_outflow_takes_the_whole_amount_in_instalments(base) -> None:  # type: ignore[no-untyped-def]
    start = base.as_of + timedelta(days=5)
    mod = ScenarioModifier(
        type="split_outflow", date=start, amount_minor=30_001, instalments=3, cadence="monthly"
    )
    assert _end_shift(base, mod) == -30_001


def test_recurring_cancel_removes_every_occurrence(base) -> None:  # type: ignore[no-untyped-def]
    ob = next(o for o in base.obligations if o.key == "rob_netflix")
    mod = ScenarioModifier(
        type="recurring_cancel", recurring_id=ob.key, from_date=base.as_of + timedelta(days=1)
    )
    shift = _end_shift(base, mod)
    assert shift > 0
    assert shift % abs(ob.amount_minor) == 0


def test_recurring_change_charges_the_new_amount(base) -> None:  # type: ignore[no-untyped-def]
    ob = next(o for o in base.obligations if o.key == "rob_netflix")
    cancel = _end_shift(base, ScenarioModifier(type="recurring_cancel", recurring_id=ob.key))
    change = _end_shift(
        base,
        ScenarioModifier(
            type="recurring_change", recurring_id=ob.key, amount_minor=abs(ob.amount_minor) + 100
        ),
    )
    months = cancel // abs(ob.amount_minor)
    assert change == -100 * months


def test_income_loss_and_category_cap_and_buffer(base) -> None:  # type: ignore[no-untyped-def]
    loss = _sim(
        base, ScenarioModifier(type="income_change_pct", income_stream_key="all_income", pct=-100)
    )
    assert loss.simulated.p50[-1] < loss.baseline.p50[-1]
    cap = _end_shift(
        base,
        ScenarioModifier(type="category_cap", category_key="food.delivery", monthly_cap_minor=0),
    )
    assert cap > 0
    buffer = _sim(base, ScenarioModifier(type="buffer_override", buffer_minor=0))
    assert buffer.simulated.p50 == buffer.baseline.p50
    assert all(
        c.chance_below_buffer in (0.0, None) or c.chance_below_buffer <= 1
        for c in buffer.simulated.pay_cycles
    )


def test_unknown_targets_are_rejected_not_guessed(base) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ScenarioError):
        _sim(base, ScenarioModifier(type="recurring_cancel", recurring_id="rob_nope"))
    with pytest.raises(ScenarioError):
        _sim(base, ScenarioModifier(type="category_cut_pct", category_key="no.such", pct=10))
    with pytest.raises(ScenarioError):
        _sim(base, ScenarioModifier(type="move_to_goal", amount_minor=100, date=date(2026, 11, 1)))
