"""Goal projection (docs/07 §6.7), `residual` funding: no money moves, and a path's progress is
the cash above the buffer at the target month's pre-salary low,

    progress[p] = max(0, pre_salary_low[p, target cycle] − buffer)

where the target cycle is the window that ends the day before the last payday on or before the
target date (or, with no payday in reach, the window from tomorrow to the target date). Paths
are the forecast's own (same seed, prior and calibration), so a goal never disagrees with the
forecast it sits beside.

Output: progress P10/P50/P90 at the target, `p_achieve` (the share of paths reaching the target),
the band (`on_track` p ≥ 0.5, `at_risk` 0.25–0.5, `off_track` < 0.25), the shortfall
(target − P50 progress; negative is a surplus), `progress_now` (P50 of the next pre-salary low −
buffer, floored at 0: what is genuinely spare today), the trajectory (each pay cycle's low
above the buffer, up to the target cycle), and the
required monthly change to reach p ≥ 0.5: bisection on a uniform monthly saving uplift (≤ 20
iterations), rounded up to the currency's goal-change increment (GBP: £10; otherwise one major
unit, never an FX conversion). Beyond 90 days the projection is labelled lower-confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction

import numpy as np

from backend.finance_core.forecast.calibration import Calibration
from backend.finance_core.forecast.engine import (
    QUANTILES,
    balance_paths,
    calibrate_paths,
    forecast_hash,
    prepare,
    quantile_minor,
)
from backend.finance_core.forecast.prior import IrregularPrior
from backend.finance_core.money import exponent
from backend.finance_core.types import ForecastInputs, Quantiles

ENGINE_VERSION = "goal-1.0.0"
MAX_HORIZON = 365
CONFIDENT_DAYS = 90
ITERATIONS = 20
MONTH_DAYS = 30  # a "month" of the uniform uplift: every 30 days from tomorrow


class GoalError(ValueError):
    """A goal the engine can't project honestly (said why, never guessed)."""


@dataclass(frozen=True)
class GoalSpec:
    goal_id: str
    name: str
    currency: str
    target_minor: int
    target_date: date


@dataclass(frozen=True)
class GoalResult:
    goal: GoalSpec
    as_of: date
    buffer_minor: int
    measured_on: date  # the last day of the target cycle's window
    progress_now_minor: int
    progress: Quantiles
    p_achieve: float
    status_band: str
    shortfall_minor: int  # target − P50 progress; negative is a surplus
    required_monthly_minor: int | None  # 0 when already likely; None when no uplift reaches it
    trajectory_dates: tuple[date, ...]
    trajectory_p10: tuple[int, ...]
    trajectory_p50: tuple[int, ...]
    trajectory_p90: tuple[int, ...]
    horizon_days: int
    lower_confidence: bool
    n_paths: int
    seed: int
    inputs_hash: str
    engine_version: str = ENGINE_VERSION


def horizon_for(as_of: date, target_date: date) -> int:
    """The forecast horizon a goal needs: at least the usual 90 days, through the target date."""
    days = (target_date - as_of).days
    if days < 1:
        raise GoalError("the goal's date has to be after the forecast starts")
    if days > MAX_HORIZON:
        raise GoalError(f"the goal's date is over {MAX_HORIZON} days after the forecast starts")
    return max(CONFIDENT_DAYS, days)


def change_increment(currency: str) -> int:
    """The step a required monthly change is rounded up to (docs/07 §6.7)."""
    unit = 10 ** exponent(currency)
    return 10 * unit if currency == "GBP" else unit


def _window(dates: tuple[date, ...], paydays: tuple[date, ...], target: date) -> tuple[int, int]:
    """[lo, hi] day indices of the target cycle (see the module docstring)."""
    index = {d: i for i, d in enumerate(dates)}
    before = [p for p in paydays if p <= target and index.get(p, 0) > 1]
    if before:
        last = before[-1]
        earlier = [p for p in paydays if p < last and p in index]
        lo = index[earlier[-1]] if earlier else 1
        return lo, index[last] - 1
    return 1, index[target]


def _band(p: float) -> str:
    return "on_track" if p >= 0.5 else "at_risk" if p >= 0.25 else "off_track"


def _q(values: np.ndarray) -> Quantiles:
    return Quantiles(*(int(quantile_minor(values, q)) for q in QUANTILES.values()))


def project_goal(
    inputs: ForecastInputs,
    goal: GoalSpec,
    *,
    prior: IrregularPrior | None = None,
    calibration: Calibration | None = None,
) -> GoalResult:
    if goal.currency != inputs.currency:
        raise GoalError(
            f"the goal is in {goal.currency} but the forecast is in {inputs.currency}; "
            "cross-currency arithmetic is not allowed"
        )
    if goal.target_minor <= 0:
        raise GoalError("a goal needs a positive target")
    if inputs.starting_balance_provenance == "relative":
        raise GoalError("a goal needs a known balance: add today's balance first")
    prep = prepare(inputs, prior)
    if goal.target_date not in set(prep.dates):
        raise GoalError("the goal's date is outside the forecast horizon")
    balances = calibrate_paths(balance_paths(prep, prep.flows), calibration)
    buffer = int(inputs.buffer_minor or 0)
    lo, hi = _window(prep.dates, prep.paydays, goal.target_date)

    def progress_with(uplift: int) -> np.ndarray:
        window = balances[:, lo : hi + 1]
        if uplift:
            days = np.arange(lo, hi + 1)
            window = window + uplift * (1 + (days - 1) // MONTH_DAYS)  # saved from tomorrow on
        return np.maximum(0, window.min(axis=1) - buffer)

    progress = progress_with(0)
    p_achieve = round(float(np.mean(progress >= goal.target_minor)), 4)
    quantiles = _q(progress)

    # What's genuinely spare today: the next pre-salary low above the buffer.
    index = {d: i for i, d in enumerate(prep.dates)}
    first = next((p for p in prep.paydays if index.get(p, 0) > 1), None)
    next_hi = index[first] - 1 if first is not None else len(prep.dates) - 1
    next_low = balances[:, 1 : next_hi + 1].min(axis=1)
    progress_now = max(0, int(quantile_minor(next_low, QUANTILES["p50"])) - buffer)

    required: int | None = 0
    if p_achieve < 0.5:
        step = change_increment(goal.currency)
        # Saving this much every month lifts even the worst path's low past the buffer and the
        # target, so the answer lies in [0, top] whenever it exists.
        top = goal.target_minor + buffer + max(0, -int(balances[:, lo : hi + 1].min()))
        if float(np.mean(progress_with(top) >= goal.target_minor)) < 0.5:
            required = None
        else:
            low, high = 0, top
            for _ in range(ITERATIONS):
                mid = (low + high) // 2
                if float(np.mean(progress_with(mid) >= goal.target_minor)) >= 0.5:
                    high = mid
                else:
                    low = mid
                if high - low <= 1:
                    break
            required = -(-high // step) * step  # rounded up to the increment

    # The trajectory is progress itself: each pay cycle's low above the buffer, up to the target
    # cycle, so the chart and the figures above it measure the same thing.
    ends: list[int] = []
    start = 1
    for pd in prep.paydays:
        end = index.get(pd, 0) - 1
        if end >= start and end <= hi:
            ends.append(end)
        if end >= hi:
            break
        start = max(start, end + 1)
    if not ends or ends[-1] != hi:
        ends.append(hi)
    starts = [1, *(e + 1 for e in ends[:-1])]
    lows = np.stack(
        [balances[:, a : e + 1].min(axis=1) for a, e in zip(starts, ends, strict=True)], 1
    )
    above = np.maximum(0, lows - buffer)
    return GoalResult(
        goal=goal,
        as_of=inputs.as_of,
        buffer_minor=buffer,
        measured_on=prep.dates[hi],
        progress_now_minor=progress_now,
        progress=quantiles,
        p_achieve=p_achieve,
        status_band=_band(p_achieve),
        shortfall_minor=goal.target_minor - quantiles.p50,
        required_monthly_minor=required,
        trajectory_dates=tuple(prep.dates[i] for i in ends),
        trajectory_p10=tuple(int(v) for v in quantile_minor(above, Fraction(1, 10))),
        trajectory_p50=tuple(int(v) for v in quantile_minor(above, Fraction(1, 2))),
        trajectory_p90=tuple(int(v) for v in quantile_minor(above, Fraction(9, 10))),
        horizon_days=inputs.horizon_days,
        lower_confidence=(goal.target_date - inputs.as_of).days > CONFIDENT_DAYS,
        n_paths=inputs.n_paths,
        seed=inputs.seed,
        inputs_hash=forecast_hash(inputs, prior, calibration, extra={"goal": goal}),
    )
