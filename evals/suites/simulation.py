"""E-SIM: simulation properties SIM-1, SIM-2, SIM-3, SIM-6 and SIM-11 on P1 (docs/09 §8).

Cases are drawn from a seeded generator (≥ 200 per property in the full run) over the P1
baseline inputs built by the E-FC pipeline at as_of. Any failure is a bug.
"""

from __future__ import annotations

import dataclasses
import random
from datetime import timedelta
from typing import Any

from backend.finance_core.calc import content_hash
from backend.finance_core.forecast.engine import build_forecast
from backend.finance_core.goals import GoalSpec, change_increment, horizon_for, project_goal
from backend.finance_core.simulate import simulate
from backend.finance_core.types import (
    Cadence,
    ForecastInputs,
    ForecastResult,
    ScenarioModifier,
    ScenarioSpec,
)
from evals.common import build_ledger, load_dataset, stable_seed
from evals.metrics import r4
from evals.suites import Target, target
from evals.suites.forecast import inputs_at

SUITE_ID = "E-SIM"
NAME = "simulation"
DATASET = "P1-base"
CASES = 200
FAST_CASES = 25
HORIZON = 90
N_PATHS = 200


def _series(r: ForecastResult) -> tuple[tuple[int, ...], ...]:
    return (r.p10, r.p50, r.p90)


def _baseline() -> ForecastInputs:
    ds = load_dataset(DATASET)
    ledger = build_ledger(ds)
    account = str(ds.accounts[0]["id"])
    inputs = inputs_at(ds, ledger, account, ds.as_of)
    return dataclasses.replace(inputs, horizon_days=HORIZON, n_paths=N_PATHS)


def _sim1(base: ForecastInputs, rng: random.Random, ctx: dict[str, int]) -> bool:
    spec = _one_off(base, rng)
    a = simulate(dataclasses.replace(base, seed=rng.randrange(2**31)), spec)
    b = simulate(dataclasses.replace(base, seed=a.baseline.seed), spec)
    return content_hash(a) == content_hash(b)


def _sim2(base: ForecastInputs, rng: random.Random, ctx: dict[str, int]) -> bool:
    inputs = dataclasses.replace(base, seed=rng.randrange(2**31))
    empty = ScenarioSpec(name="zero", currency=inputs.currency, modifiers=())
    sim = simulate(inputs, empty).simulated
    return _series(sim) == _series(build_forecast(inputs))


def _one_off(base: ForecastInputs, rng: random.Random) -> ScenarioSpec:
    day = base.as_of + timedelta(days=rng.randint(1, HORIZON))
    amount = rng.randint(1, 300_000)
    return ScenarioSpec(
        name="one-off",
        currency=base.currency,
        modifiers=(ScenarioModifier(type="one_off_outflow", date=day, amount_minor=amount),),
    )


def _sim3(base: ForecastInputs, rng: random.Random, ctx: dict[str, int]) -> bool:
    inputs = dataclasses.replace(base, seed=rng.randrange(2**31))
    spec = _one_off(inputs, rng)
    mod = spec.modifiers[0]
    assert mod.date is not None
    assert mod.amount_minor is not None
    res = simulate(inputs, spec)
    worst = 0
    for b, s in zip(_series(res.baseline), _series(res.simulated), strict=True):
        for k, (bv, sv) in enumerate(zip(b, s, strict=True)):
            expected = bv - mod.amount_minor * (res.baseline.dates[k] >= mod.date)
            worst = max(worst, abs(sv - expected))
    ctx["max_abs_deviation_minor"] = max(ctx.get("max_abs_deviation_minor", 0), worst)
    return worst == 0


def _sim6(base: ForecastInputs, rng: random.Random, ctx: dict[str, int]) -> bool | None:
    inputs = dataclasses.replace(base, seed=rng.randrange(2**31))
    streams = [
        s
        for s in inputs.income_streams
        if s.cadence is not Cadence.IRREGULAR and s.payday_rule is not None
    ]
    if not streams:
        return None
    stream = streams[0]
    k = rng.randint(1, 10)
    spec = ScenarioSpec(
        name="delay",
        currency=inputs.currency,
        modifiers=(
            ScenarioModifier(
                type="income_delay", income_stream_key=stream.key, days=k, occurrences=1
            ),
        ),
    )
    res = simulate(inputs, spec)
    dates = res.baseline.dates
    changed = [
        dates[i]
        for i in range(len(dates))
        if any(
            b[i] != s[i] for b, s in zip(_series(res.baseline), _series(res.simulated), strict=True)
        )
    ]
    if not changed:
        return True  # pay outside the horizon window: nothing moves
    pay, new_day = changed[0], changed[-1] + timedelta(days=1)
    contiguous = changed == [pay + timedelta(days=i) for i in range((new_day - pay).days)]
    shifted_by_at_least_k = (new_day - pay).days >= k
    end_same = new_day > dates[-1] or all(
        b[-1] == s[-1] for b, s in zip(_series(res.baseline), _series(res.simulated), strict=True)
    )
    return contiguous and shifted_by_at_least_k and end_same


def _sim11(base: ForecastInputs, rng: random.Random, ctx: dict[str, int]) -> bool:
    """Goal consistency (docs/09 §8, docs/07 §6.7, `residual`): the shortfall is the target less
    P50 progress to the penny; P50 progress is the forecast's own target-cycle low above the
    buffer whenever the zero floor can't reach the median; the required change is whole steps;
    and the projection is deterministic."""
    target_date = base.as_of + timedelta(days=rng.randint(30, 300))
    inputs = dataclasses.replace(
        base,
        seed=rng.randrange(2**31),
        horizon_days=horizon_for(base.as_of, target_date),
    )
    goal = GoalSpec("goal_sim11", "Goal", inputs.currency, rng.randint(1, 1_000_000), target_date)
    r = project_goal(inputs, goal)
    ok = r.shortfall_minor == goal.target_minor - r.progress.p50
    ok = ok and r == project_goal(inputs, goal)
    forecast = build_forecast(inputs)
    paydays = [c.payday for c in forecast.pay_cycles if c.payday <= target_date]
    buffer = int(inputs.buffer_minor or 0)
    if paydays:
        cycle = next(c for c in forecast.pay_cycles if c.payday == paydays[-1])
        # Exact only when the zero floor can't reach the median's order statistics: clearly
        # fewer than half the paths end the cycle below the buffer.
        if cycle.chance_below_buffer is not None and cycle.chance_below_buffer < 0.45:
            ctx["cross_checked"] = ctx.get("cross_checked", 0) + 1
            ok = ok and r.progress.p50 == cycle.low.p50 - buffer
    step = change_increment(inputs.currency)
    return ok and (r.required_monthly_minor is None or r.required_monthly_minor % step == 0)


PROPERTIES = {
    "SIM-1": ("Determinism", _sim1),
    "SIM-2": ("Zero scenario = baseline", _sim2),
    "SIM-3": ("One-off linearity", _sim3),
    "SIM-6": ("Income-delay conservation", _sim6),
    "SIM-11": ("Goal consistency", _sim11),
}


def run(fast: bool = False) -> dict[str, Any]:
    base = _baseline()
    n = FAST_CASES if fast else CASES
    results: dict[str, Any] = {}
    passed_all = total_all = 0
    for pid, (label, fn) in PROPERTIES.items():
        rng = random.Random(stable_seed(DATASET, pid))  # noqa: S311 - test cases, not secrets
        passed = failed = skipped = 0
        first_failure: int | None = None
        ctx: dict[str, int] = {}
        for case in range(n):
            ok = fn(base, rng, ctx)
            if ok is None:
                skipped += 1
            elif ok:
                passed += 1
            else:
                failed += 1
                first_failure = case if first_failure is None else first_failure
        results[pid] = {
            "label": label,
            "cases": n,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "first_failing_case": first_failure,
            **ctx,
        }
        passed_all += passed
        total_all += passed + failed
    metrics: dict[str, Any] = {
        "dataset": DATASET,
        "as_of": base.as_of.isoformat(),
        "horizon_days": HORIZON,
        "n_paths": N_PATHS,
        "properties": results,
        "passed": passed_all,
        "total": total_all,
        "pass_rate": r4(passed_all / total_all) if total_all else None,
        "not_run": [
            "SIM-4",
            "SIM-5",
            "SIM-7",
            "SIM-8",
            "SIM-9",
            "SIM-10",
            "SIM-12",
            "SIM-13",
        ],
    }
    targets: list[Target] = [
        target(
            "SIM", "Properties passed (SIM-1/2/3/6/11)", metrics["pass_rate"], ">=", 1.0, DATASET
        ),
    ]
    notes = [
        f"{n} seeded cases per property; one-off amounts £0.01–£3,000 on a random horizon day; "
        "income delays of 1–10 days on the first payday in the horizon.",
        "SIM-6 checks that only a contiguous window starting at the payday changes, that it spans "
        "at least the delay, and that the end balance is unchanged when the pay lands in horizon.",
        "SIM-11 projects a goal (target £0.01–£10,000, 30–300 days out, residual funding): the "
        "shortfall must equal target − P50 progress to the penny, the projection must repeat "
        "exactly, the required monthly change must be whole £10 steps, and P50 progress must equal "
        "the forecast's own target-cycle low above the buffer whenever under 45% of paths dip "
        "below the buffer (otherwise the zero floor reaches the median and the two may differ).",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
