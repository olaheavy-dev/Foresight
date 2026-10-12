"""What-if simulation on the same engine with common random numbers (docs/07 §6.5).

The scenario reuses the baseline's discretionary draws and seed, so every difference between the
baseline and the simulated result comes from the scenario's modifiers, never from randomness.
v1 modifiers: one_off_outflow, one_off_inflow, income_delay.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

from backend.finance_core.calc import content_hash
from backend.finance_core.forecast._calendar import next_working_day
from backend.finance_core.forecast.engine import (
    Flow,
    balance_paths,
    pay_cycle_lows,
    prepare,
    summarise,
)
from backend.finance_core.types import (
    ForecastInputs,
    ScenarioModifier,
    ScenarioSpec,
    SimulationResult,
)

SUPPORTED = frozenset({"one_off_outflow", "one_off_inflow", "income_delay"})


class ScenarioError(ValueError):
    """A scenario that cannot be simulated as specified (never guessed or silently fixed)."""


def _apply(
    flows: list[Flow], mod: ScenarioModifier, inputs: ForecastInputs, dates_index: dict[date, int]
) -> list[Flow]:
    if mod.type in ("one_off_outflow", "one_off_inflow"):
        if mod.date is None or mod.amount_minor is None or mod.amount_minor <= 0:
            raise ScenarioError(f"{mod.type} needs a date and a positive amount")
        if mod.date <= inputs.as_of or mod.date not in dates_index:
            raise ScenarioError(f"{mod.type} date {mod.date} is outside the forecast horizon")
        sign = -1 if mod.type == "one_off_outflow" else 1
        label = mod.label or mod.type
        return [*flows, Flow(dates_index[mod.date], sign * mod.amount_minor, label)]
    if mod.type == "income_delay":
        if mod.income_stream_key is None or mod.days is None or mod.days <= 0:
            raise ScenarioError("income_delay needs an income stream and a positive number of days")
        targets = sorted(
            (f for f in flows if f.income_key == mod.income_stream_key), key=lambda f: f.day
        )
        if not targets:
            raise ScenarioError(f"no paydays for income stream {mod.income_stream_key!r}")
        chosen = targets if mod.occurrences is None else targets[: mod.occurrences]
        ids = {id(f) for f in chosen}
        dates = sorted(dates_index, key=dates_index.__getitem__)
        out: list[Flow] = []
        for f in flows:
            if id(f) not in ids:
                out.append(f)
                continue
            # Delayed pay lands on the next working day on or after the delayed date.
            new_date = next_working_day(dates[f.day] + timedelta(days=mod.days), inputs.holidays)
            if new_date in dates_index:  # beyond the horizon: the money leaves the forecast
                out.append(dataclasses.replace(f, day=dates_index[new_date]))
        return out
    raise ScenarioError(f"unsupported modifier {mod.type!r}; v1 supports {sorted(SUPPORTED)}")


def simulate(baseline_inputs: ForecastInputs, spec: ScenarioSpec) -> SimulationResult:
    if spec.currency != baseline_inputs.currency:
        raise ScenarioError(
            f"scenario currency {spec.currency} differs from the forecast currency "
            f"{baseline_inputs.currency}; cross-currency arithmetic is not allowed"
        )
    inputs = baseline_inputs
    if spec.horizon_days is not None and spec.horizon_days != inputs.horizon_days:
        inputs = dataclasses.replace(inputs, horizon_days=spec.horizon_days)
    prep = prepare(inputs)
    index = {d: i for i, d in enumerate(prep.dates)}
    flows = list(prep.flows)
    for mod in spec.modifiers:
        flows = _apply(flows, mod, inputs, index)

    base_balances = balance_paths(prep, prep.flows)
    sim_balances = balance_paths(prep, flows)
    sim_paydays = sorted({prep.dates[f.day] for f in flows if f.income_key is not None})

    baseline = summarise(prep, base_balances, content_hash(inputs))
    simulated = summarise(
        prep,
        sim_balances,
        content_hash({"inputs": inputs, "scenario": spec}),
        cycle_paydays=sim_paydays,
    )
    # Compare like with like: both lows measured over the baseline's pay-cycle windows.
    sim_on_base = pay_cycle_lows(prep, sim_balances, prep.paydays)
    delta = tuple(
        (b.payday, b.low.p50, s.low.p50)
        for b, s in zip(baseline.pay_cycles, sim_on_base, strict=True)
    )
    return SimulationResult(scenario=spec, baseline=baseline, simulated=simulated, delta_lows=delta)
