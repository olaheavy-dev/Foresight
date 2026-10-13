"""Rolling-origin backtest against naive baselines (docs/09 §7, docs/07 §6.8).

Given a reconstructed daily balance history and a function that builds ForecastInputs as they
would have been known at an origin (truncated ledger), compare the forecast with what actually
happened, and do the same for four naive baselines.

With `calibrate=True` the forecast at each origin is calibrated (§6.8a) from the engine's own raw
forecasts at earlier origins, scored only on balances up to the origin, exactly as the product
does for a user: nothing after the origin is used. `calibration_origins` adds earlier origins
whose raw forecasts serve only as calibration windows (they are not scored).

Error measures, per horizon h:
- MAE of the P50 in minor units;
- MASE (Hyndman and Koehler, 2006): the absolute error divided by the in-sample mean absolute
  h-step change of the balance before the origin (the error of the naive "no change" forecast
  inside the history), averaged over origins. Below 1 the forecast beats in-sample naive;
- MAPE, reported for continuity only: it divides by the balance, which is near zero exactly at
  the pre-payday lows that matter most, so it is not used as a target.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from statistics import fmean
from typing import Any

import numpy as np

from backend.finance_core.forecast.calibration import PastForecast, fit_calibration
from backend.finance_core.forecast.engine import build_forecast
from backend.finance_core.forecast.prior import IrregularPrior
from backend.finance_core.types import ForecastInputs, ForecastResult

DEFAULT_HORIZONS = (7, 30, 60)
BASELINES = ("B0", "B1", "B2", "B3")
PINBALL_QUANTILES = (0.1, 0.5, 0.9)


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


def _pinball(actual: int, preds: Sequence[int]) -> float:
    """Mean quantile (pinball) loss of the P10/P50/P90 forecasts for one day."""
    total = 0.0
    for q, p in zip(PINBALL_QUANTILES, preds, strict=True):
        diff = actual - p
        total += max(q * diff, (q - 1) * diff)
    return total / len(PINBALL_QUANTILES)


class _NaiveScale:
    """In-sample mean absolute h-step change of the balance, for MASE."""

    def __init__(self, history: Mapping[date, int]) -> None:
        days = sorted(history)
        self.first = days[0] if days else date.min
        n = (days[-1] - self.first).days + 1 if days else 0
        self.values = np.full(n, np.nan)
        for d in days:
            self.values[(d - self.first).days] = history[d]

    def at(self, origin: date, h: int) -> float | None:
        end = (origin - self.first).days  # last usable index for t + h
        if end < h:
            return None
        y = self.values[: end + 1]
        diffs = np.abs(y[h:] - y[:-h])
        diffs = diffs[~np.isnan(diffs)]
        if diffs.size == 0:
            return None
        scale = float(diffs.mean())
        return scale if scale > 0 else None


def _origin_record(
    origin: date,
    fc: ForecastResult,
    baselines: Mapping[str, Sequence[int]],
    actual: Sequence[int | None],
    horizons: Sequence[int],
    naive: _NaiveScale,
    calibrated: bool,
) -> dict[str, Any]:
    covered = days = 0
    pinball = 0.0
    for k, a in enumerate(actual):
        if a is None:
            continue
        days += 1
        covered += int(fc.p10[k + 1] <= a <= fc.p90[k + 1])
        pinball += _pinball(a, (fc.p10[k + 1], fc.p50[k + 1], fc.p90[k + 1]))
    rec: dict[str, Any] = {
        "origin": origin.isoformat(),
        "calibrated": calibrated,
        "days": days,
        "covered": covered,
        "pinball_minor": round(pinball, 2),
        "ae_minor": {},
        "ape": {},
        "naive_scale_minor": {},
        "baseline_ae_minor": {b: {} for b in baselines},
    }
    for h in horizons:
        a = actual[h - 1] if h - 1 < len(actual) else None
        key = str(h)
        scale = naive.at(origin, h)
        rec["naive_scale_minor"][key] = None if scale is None else round(scale, 2)
        if a is None:
            rec["ae_minor"][key] = rec["ape"][key] = None
            for b in baselines:
                rec["baseline_ae_minor"][b][key] = None
            continue
        err = abs(fc.p50[h] - a)
        rec["ae_minor"][key] = err
        rec["ape"][key] = round(err / abs(a), 6) if a != 0 else None
        for b, pred in baselines.items():
            rec["baseline_ae_minor"][b][key] = abs(pred[h - 1] - a)
    return rec


def _mean(values: Sequence[float]) -> float | None:
    return round(fmean(values), 4) if values else None


def _scaled(errors: Sequence[tuple[int, float | None]]) -> float | None:
    return _mean([e / s for e, s in errors if s])


def summarise_origins(rows: Sequence[Mapping[str, Any]], horizons: Sequence[int]) -> dict[str, Any]:
    """Aggregate per-origin records: MAE, MASE, MAPE per horizon, coverage and pinball over all
    scored days, and the same MAE/MASE for every baseline."""
    days = sum(r["days"] for r in rows)
    out: dict[str, Any] = {
        "n_origins": len(rows),
        "coverage_p10_p90": round(sum(r["covered"] for r in rows) / days, 4) if days else None,
        "pinball_minor": round(sum(r["pinball_minor"] for r in rows) / days, 2) if days else None,
        "mae_minor": {},
        "mase": {},
        "mape": {},
        "baselines": {},
    }
    names = sorted({b for r in rows for b in r["baseline_ae_minor"]})
    for h in horizons:
        key = str(h)
        scored = [r for r in rows if r["ae_minor"][key] is not None]
        out["mae_minor"][key] = _mean([float(r["ae_minor"][key]) for r in scored])
        out["mape"][key] = _mean([r["ape"][key] for r in scored if r["ape"][key] is not None])
        out["mase"][key] = _scaled(
            [(r["ae_minor"][key], r["naive_scale_minor"][key]) for r in scored]
        )
    for b in names:
        out["baselines"][b] = {"mae_minor": {}, "mase": {}}
        for h in horizons:
            key = str(h)
            scored = [r for r in rows if r["baseline_ae_minor"][b][key] is not None]
            out["baselines"][b]["mae_minor"][key] = _mean(
                [float(r["baseline_ae_minor"][b][key]) for r in scored]
            )
            out["baselines"][b]["mase"][key] = _scaled(
                [(r["baseline_ae_minor"][b][key], r["naive_scale_minor"][key]) for r in scored]
            )
    return out


def backtest(
    history: Mapping[date, int],
    origins: Sequence[date],
    build_inputs: Callable[[date], ForecastInputs],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    *,
    prior: IrregularPrior | None = None,
    calibrate: bool = False,
    calibration_origins: Sequence[date] = (),
) -> dict[str, Any]:
    """Run the forecast at each origin and score it against history and baselines B0–B3.

    Returns a JSON-ready dict: per-horizon MAE (minor units), MASE and MAPE for Foresight and each
    baseline, P10–P90 coverage, mean pinball loss over P10/P50/P90 (minor units), pay-cycle-low
    error, skill versus B1, and the per-origin records (for dev/test splits).
    """
    max_h = max(horizons)
    scored_origins = set(origins)
    sweep = sorted(scored_origins | (set(calibration_origins) if calibrate else set()))
    naive = _NaiveScale(history)
    past: list[PastForecast] = []
    rows: list[dict[str, Any]] = []
    low_errors: list[float] = []
    for origin in sweep:
        if origin not in history:
            raise ValueError(f"no balance history on origin {origin}")
        inputs = dataclasses.replace(build_inputs(origin), horizon_days=max_h)
        raw = build_forecast(inputs, prior=prior)
        if origin in scored_origins:
            fc, calibrated = raw, False
            if calibrate:
                cal = fit_calibration(past, history, origin)
                if cal.calibrated:
                    fc = build_forecast(inputs, prior=prior, calibration=cal)
                    calibrated = True
            cal_only = build_forecast(
                dataclasses.replace(inputs, discretionary_history=(), n_paths=1)
            )
            actual = [history.get(origin + timedelta(days=k + 1)) for k in range(max_h)]
            baselines = _baseline_forecasts(history, origin, max_h, cal_only)
            rows.append(_origin_record(origin, fc, baselines, actual, horizons, naive, calibrated))
            for i, cycle in enumerate(fc.pay_cycles):
                window_start = origin + timedelta(days=1) if i == 0 else fc.pay_cycles[i - 1].payday
                span = (cycle.payday - window_start).days
                window = [window_start + timedelta(days=j) for j in range(span)]
                vals = [history[d] for d in window if d in history]
                if window and len(vals) == len(window):
                    low_errors.append(abs(cycle.low.p50 - min(vals)))
        past.append(PastForecast(origin, raw.p10, raw.p50, raw.p90))

    summary = summarise_origins(rows, horizons)
    result: dict[str, Any] = {
        "n_origins": len(rows),
        "horizons": list(horizons),
        "foresight": {
            "mae_minor": summary["mae_minor"],
            "mase": summary["mase"],
            "mape": summary["mape"],
            "coverage_p10_p90": summary["coverage_p10_p90"],
            "pinball_minor": summary["pinball_minor"],
            "pay_cycle_low_mae_minor": round(fmean(low_errors), 2) if low_errors else None,
            "calibrated_origins": sum(1 for r in rows if r["calibrated"]),
        },
        "baselines": {
            name: {
                "mae_minor": summary["baselines"][name]["mae_minor"],
                "mase": summary["baselines"][name]["mase"],
            }
            for name in BASELINES
        },
        "per_origin": rows,
    }
    skill: dict[str, float | None] = {}
    for h in horizons:
        ours_h = result["foresight"]["mae_minor"][str(h)]
        b1_h = result["baselines"]["B1"]["mae_minor"][str(h)]
        skill[str(h)] = round(1 - ours_h / b1_h, 4) if ours_h is not None and b1_h else None
    result["skill_vs_B1"] = skill
    return result
