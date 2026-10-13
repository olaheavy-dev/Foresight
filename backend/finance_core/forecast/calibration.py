"""Self-calibrating P10–P90 bands (docs/07 §6.8a, docs/06 §10.4).

The engine's band comes from its own model of uncertainty. Whether that band is honest is an
empirical question, so before each forecast we score the engine's earlier forecasts for the same
user against what actually happened, and widen the spread around the median until the band would
have covered 80% of the realised balances (split-conformal prediction with normalised scores, in
the style of conformalised quantile regression: Romano, Patterson and Candès, NeurIPS 2019).

For a past forecast with median m, lower quantile q10 and upper quantile q90 on horizon day h,
and the realised balance y, the score is how far the band would have had to stretch about the
median to cover y:

    r = (m − y) / (m − q10)  if y < m
    r = (y − m) / (q90 − m)  if y > m
    r = 0                    if y = m

The scale for a horizon bucket is the conformal quantile of its scores at level 0.8 (finite-sample
corrected: the ⌈(n + 1) · 0.8⌉-th smallest), so the stretched band would have covered about 80%.

Choices, made on dev origins only (docs/09 §3.8; measurements in docs/07 §6.8a):
- one scale for both tails: separate tail scales chased a bias that changed sign over time and
  made the band worse on every persona;
- widen only (scale ≥ 1): where the engine's band already covers 80% it is kept, so calibration
  never narrows a band on thin evidence;
- scores from forecasts made in the last MAX_LOOKBACK_DAYS only, and a bucket needs MIN_WINDOWS
  past forecasts before it is calibrated; below that the engine's own band stands (it carries the
  irregular-expense prior for short histories, prior.py).

Only forecasts made before `as_of`, scored on days up to `as_of`, are used: nothing after the
forecast origin.

Applying a scale transforms every path on that day: b' = m + s · (b − m), with m the day's exact
integer median and the product rounded half up in integers. The transform is monotone, so every
statistic computed from the paths afterwards (pay-cycle lows, breach chances) is calibrated
consistently with the band, and adding a constant to every path still moves every quantile by
exactly that constant.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction
from math import ceil
from typing import Any

import numpy as np
import numpy.typing as npt

CALIBRATION_VERSION = "cal-1"
COVERAGE = Fraction(4, 5)  # the P10–P90 band should cover 80% of outcomes
# Horizon buckets (inclusive day ranges). Scales are fitted per bucket because the spread grows
# with the horizon and miscalibration differs between the next week and the next two months.
BUCKETS: tuple[tuple[int, int], ...] = ((1, 7), (8, 14), (15, 30), (31, 60), (61, 90))
MIN_WINDOWS = 4  # past forecasts with realised days in a bucket before it is calibrated
MAX_LOOKBACK_DAYS = 91  # only forecasts made in the last ~3 months are scored
SCALE_BOUNDS = (Fraction(1), Fraction(4))  # widen only, at most 4×
SCALE_DENOMINATOR = 1000  # scales are rounded to 1/1000 so integer arithmetic stays small

IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class PastForecast:
    """The band of an earlier forecast: index 0 is its origin, index h is origin + h days."""

    origin: date
    p10: tuple[int, ...]
    p50: tuple[int, ...]
    p90: tuple[int, ...]


@dataclass(frozen=True)
class BucketScale:
    first_day: int
    last_day: int
    windows: int  # past forecasts that contributed at least one realised day
    points: int  # realised (forecast, day) pairs scored
    scale: Fraction | None  # None: too few windows, the engine's band is kept
    raw_coverage: float | None  # how often the uncalibrated band covered (for the record)


@dataclass(frozen=True)
class Calibration:
    version: str
    as_of: date
    buckets: tuple[BucketScale, ...]

    def scale(self, day: int) -> Fraction:
        """Scale for horizon day `day` (1 where uncalibrated; beyond the last bucket, its scale)."""
        for b in self.buckets:
            if b.first_day <= day <= b.last_day:
                return b.scale or Fraction(1)
        if self.buckets and day > self.buckets[-1].last_day:
            return self.buckets[-1].scale or Fraction(1)
        return Fraction(1)

    @property
    def calibrated(self) -> bool:
        return any(b.scale is not None and b.scale != 1 for b in self.buckets)


def _conformal(scores: Sequence[Fraction]) -> Fraction:
    """The ⌈(n + 1) · COVERAGE⌉-th smallest score (the largest if that exceeds n)."""
    ordered = sorted(scores)
    n = len(ordered)
    k = ceil((n + 1) * COVERAGE)
    return ordered[min(k, n) - 1]


def _clamp(s: Fraction) -> Fraction:
    lo, hi = SCALE_BOUNDS
    return min(max(s, lo), hi).limit_denominator(SCALE_DENOMINATOR)


def _bucket_of(day: int) -> int | None:
    for i, (first, last) in enumerate(BUCKETS):
        if first <= day <= last:
            return i
    return None


def _score(y: int, m: int, q10: int, q90: int) -> Fraction:
    if y < m:
        return Fraction(m - y, max(1, m - q10))
    if y > m:
        return Fraction(y - m, max(1, q90 - m))
    return Fraction(0)


def fit_calibration(
    past: Sequence[PastForecast], actual: Mapping[date, int], as_of: date
) -> Calibration:
    """Fit a widening scale per horizon bucket from forecasts made before `as_of`, scored only on
    realised balances on or before `as_of`."""
    oldest = as_of - timedelta(days=MAX_LOOKBACK_DAYS)
    scores: list[list[Fraction]] = [[] for _ in BUCKETS]
    covered = [0 for _ in BUCKETS]
    windows: list[set[date]] = [set() for _ in BUCKETS]
    for pf in past:
        if not (oldest <= pf.origin < as_of):
            continue
        for h in range(1, len(pf.p50)):
            day = pf.origin + timedelta(days=h)
            if day > as_of:
                break
            b = _bucket_of(h)
            y = actual.get(day)
            if b is None or y is None:
                continue
            scores[b].append(_score(y, pf.p50[h], pf.p10[h], pf.p90[h]))
            covered[b] += int(pf.p10[h] <= y <= pf.p90[h])
            windows[b].add(pf.origin)
    buckets = tuple(
        BucketScale(
            first_day=first,
            last_day=last,
            windows=len(windows[i]),
            points=len(scores[i]),
            scale=_clamp(_conformal(scores[i])) if len(windows[i]) >= MIN_WINDOWS else None,
            raw_coverage=round(covered[i] / len(scores[i]), 4) if scores[i] else None,
        )
        for i, (first, last) in enumerate(BUCKETS)
    )
    return Calibration(CALIBRATION_VERSION, as_of, buckets)


def apply_calibration(balances: IntArray, medians: IntArray, cal: Calibration) -> IntArray:
    """b' = m + s · (b − m) per day. Column 0 (today) is left as it is."""
    n_days = balances.shape[1]
    num = np.ones(n_days, dtype=np.int64)
    den = np.ones(n_days, dtype=np.int64)
    for t in range(1, n_days):
        s = cal.scale(t)
        num[t], den[t] = s.numerator, s.denominator
    dev = balances - medians[None, :]
    scaled = np.floor_divide(2 * dev * num[None, :] + den[None, :], 2 * den[None, :])
    return np.asarray(medians[None, :] + scaled, dtype=np.int64)


def to_jsonable(cal: Calibration) -> dict[str, object]:
    """A stable, JSON-ready description (stored with the forecast and hashed into its id)."""
    return {
        "version": cal.version,
        "as_of": cal.as_of.isoformat(),
        "buckets": [
            {
                "days": [b.first_day, b.last_day],
                "windows": b.windows,
                "points": b.points,
                "scale": None if b.scale is None else str(b.scale),
                "raw_coverage": b.raw_coverage,
            }
            for b in cal.buckets
        ],
    }


def from_jsonable(data: Mapping[str, Any]) -> Calibration:
    """Inverse of to_jsonable (used to recompute a stored forecast exactly)."""
    buckets = tuple(
        BucketScale(
            first_day=int(b["days"][0]),
            last_day=int(b["days"][1]),
            windows=int(b["windows"]),
            points=int(b["points"]),
            scale=None if b["scale"] is None else Fraction(str(b["scale"])),
            raw_coverage=b["raw_coverage"],
        )
        for b in data["buckets"]
    )
    return Calibration(str(data["version"]), date.fromisoformat(str(data["as_of"])), buckets)
