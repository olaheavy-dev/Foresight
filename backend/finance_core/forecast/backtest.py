"""Rolling-origin backtest against naive baselines (docs/09 §7, docs/07 §6.8).

Given a reconstructed daily balance history and a function that builds ForecastInputs as they
would have been known at an origin (truncated ledger), compare the forecast's P50 with what
actually happened, and do the same for four naive baselines.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from statistics import fmean
from typing import Any

from backend.finance_core.forecast.engine import build_forecast
from backend.finance_core.types import ForecastInputs, ForecastResult

DEFAULT_HORIZONS = (7, 30, 60)
BASELINES = ("B0", "B1", "B2", "B3")


def _baseline_forecasts(
    history: Mapping[date, int], origin: date, max_h: int, calendar_only: ForecastResult
) -> dict[str, list[int]]:
    """Point forecasts for days origin+1..origin+max_h (index 0 = origin+1)."""
    start = history[origin]
    lookback = [history.get(origin - timedelta(days=30 - k)) for k in range(31)]
    known = [v for v in lookback if v is not None]
    nets = [
        b - a
        for a, b in zip(lookback, lookback[1:], strict=False)
        if a is not None and b is not None
    ]
    b1: list[int] = []
    bal = start
    for k in range(max_h):
        bal += nets[k % len(nets)] if nets else 0
        b1.append(bal)
    mean_net = (known[-1] - known[0]) / max(1, len(known) - 1) if len(known) > 1 else 0.0
    return {
        "B0": [start] * max_h,  # flat last balance
        "B1": b1,  # repeat the last 30 days of daily net flows
        "B2": [round(start + mean_net * (k + 1)) for k in range(max_h)],  # trailing mean
        "B3": list(calendar_only.p50[1 : max_h + 1]),  # calendar only, no discretionary
    }


Metric = dict[str, dict[str, float | None]]


def _errors(pred: Sequence[int], actual: Sequence[int | None], horizons: Sequence[int]) -> Metric:
    out: Metric = {"mae_minor": {}, "mape": {}}
    for h in horizons:
        a = actual[h - 1] if h - 1 < len(actual) else None
        if a is None or h - 1 >= len(pred):
            out["mae_minor"][str(h)] = None
            out["mape"][str(h)] = None
            continue
        err = abs(pred[h - 1] - a)
        out["mae_minor"][str(h)] = float(err)
        out["mape"][str(h)] = float(err / abs(a)) if a != 0 else None
    return out


def _mean_by_horizon(
    per_origin: list[Metric], metric: str, horizons: Sequence[int]
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for h in horizons:
        vals = [v for o in per_origin if (v := o[metric][str(h)]) is not None]
        out[str(h)] = round(fmean(vals), 4) if vals else None
    return out


def backtest(
    history: Mapping[date, int],
    origins: Sequence[date],
    build_inputs: Callable[[date], ForecastInputs],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """Run the forecast at each origin and score it against history and baselines B0–B3.

    Returns a JSON-ready dict: per-horizon MAE (minor units) and MAPE for Foresight and each
    baseline, P10–P90 coverage, pay-cycle-low error and skill versus B1.
    """
    max_h = max(horizons)
    ours: list[Metric] = []
    base: dict[str, list[Metric]] = {b: [] for b in BASELINES}
    covered = total = 0
    low_errors: list[float] = []
    for origin in origins:
        if origin not in history:
            raise ValueError(f"no balance history on origin {origin}")
        inputs = dataclasses.replace(build_inputs(origin), horizon_days=max_h)
        fc = build_forecast(inputs)
        cal = build_forecast(dataclasses.replace(inputs, discretionary_history=(), n_paths=1))
        actual = [history.get(origin + timedelta(days=k + 1)) for k in range(max_h)]
        ours.append(_errors(list(fc.p50[1:]), actual, horizons))
        for name, pred in _baseline_forecasts(history, origin, max_h, cal).items():
            base[name].append(_errors(pred, actual, horizons))
        for k, a in enumerate(actual):
            if a is not None:
                total += 1
                covered += int(fc.p10[k + 1] <= a <= fc.p90[k + 1])
        for cycle in fc.pay_cycles:
            window_start = (
                origin + timedelta(days=1)
                if cycle is fc.pay_cycles[0]
                else fc.pay_cycles[fc.pay_cycles.index(cycle) - 1].payday
            )
            span = (cycle.payday - window_start).days
            days = [window_start + timedelta(days=i) for i in range(span)]
            vals = [history[d] for d in days if d in history]
            if days and len(vals) == len(days):
                low_errors.append(abs(cycle.low.p50 - min(vals)))

    result: dict[str, Any] = {
        "n_origins": len(origins),
        "horizons": list(horizons),
        "foresight": {
            "mae_minor": _mean_by_horizon(ours, "mae_minor", horizons),
            "mape": _mean_by_horizon(ours, "mape", horizons),
            "coverage_p10_p90": round(covered / total, 4) if total else None,
            "pay_cycle_low_mae_minor": round(fmean(low_errors), 2) if low_errors else None,
        },
        "baselines": {
            name: {
                "mae_minor": _mean_by_horizon(rows, "mae_minor", horizons),
                "mape": _mean_by_horizon(rows, "mape", horizons),
            }
            for name, rows in base.items()
        },
    }
    skill: dict[str, float | None] = {}
    for h in horizons:
        ours_h = result["foresight"]["mae_minor"][str(h)]
        b1_h = result["baselines"]["B1"]["mae_minor"][str(h)]
        skill[str(h)] = round(1 - ours_h / b1_h, 4) if ours_h is not None and b1_h else None
    result["skill_vs_B1"] = skill
    return result
