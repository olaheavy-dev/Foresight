"""Engine v1.3: band calibration (docs/07 §6.8a), irregular-expense prior (§6.2b) and MASE."""

from __future__ import annotations

from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from backend.finance_core.calc import content_hash
from backend.finance_core.forecast.backtest import backtest
from backend.finance_core.forecast.calibration import (
    MIN_WINDOWS,
    Calibration,
    PastForecast,
    apply_calibration,
    fit_calibration,
    from_jsonable,
    to_jsonable,
)
from backend.finance_core.forecast.engine import (
    build_forecast,
    prepare,
    quantile_minor,
)
from backend.finance_core.forecast.prior import (
    household_scale,
    load_irregular_prior,
    prior_weight,
)
from backend.finance_core.types import ForecastInputs

from .conftest import AS_OF, history, make_inputs

PRIOR_FILE = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "finance_core"
    / "locale_packs"
    / "uk_irregular_expenses.yaml"
)
UK_PRIOR = load_irregular_prior(PRIOR_FILE.read_text(encoding="utf-8"))


def _past(origin: date, width: int, horizon: int = 30, level: int = 100_000) -> PastForecast:
    """A flat forecast at `level` with a symmetric band of ± `width`."""
    return PastForecast(
        origin,
        p10=tuple([level - width] * (horizon + 1)),
        p50=tuple([level] * (horizon + 1)),
        p90=tuple([level + width] * (horizon + 1)),
    )


def _actual(start: date, days: int, wiggle: int) -> dict[date, int]:
    """Balances alternating ± wiggle around the forecast level."""
    return {
        start + timedelta(days=i): 100_000 + (wiggle if i % 2 else -wiggle) for i in range(days)
    }


# ---------------------------------------------------------------- calibration


def test_calibration_widens_an_overconfident_band_and_covers_80_percent() -> None:
    as_of = date(2026, 6, 30)
    past = [_past(as_of - timedelta(days=7 * k), width=1_000) for k in range(1, 9)]
    actual = _actual(as_of - timedelta(days=80), 81, wiggle=3_000)  # always outside the band
    cal = fit_calibration(past, actual, as_of)
    assert cal.calibrated
    s = cal.scale(1)
    assert s == 3  # stretching ±1,000 by 3 just covers ±3,000
    # the stretched band covers the calibration points
    covered = sum(int(100_000 - s * 1_000 <= y <= 100_000 + s * 1_000) for y in actual.values())
    assert covered / len(actual) >= 0.8


def test_calibration_never_narrows_a_band_that_already_covers() -> None:
    as_of = date(2026, 6, 30)
    past = [_past(as_of - timedelta(days=7 * k), width=5_000) for k in range(1, 9)]
    actual = _actual(as_of - timedelta(days=80), 81, wiggle=100)
    cal = fit_calibration(past, actual, as_of)
    assert all(b.scale is None or b.scale == 1 for b in cal.buckets)
    assert not cal.calibrated


def test_calibration_uses_nothing_after_as_of() -> None:
    as_of = date(2026, 6, 30)
    past = [_past(as_of - timedelta(days=7 * k), width=1_000) for k in range(1, 9)]
    before = _actual(as_of - timedelta(days=80), 81, wiggle=2_000)
    after = {as_of + timedelta(days=i): 10**9 for i in range(1, 60)}  # absurd future balances
    future_forecast = _past(as_of + timedelta(days=1), width=1)  # made after as_of
    with_future = fit_calibration([*past, future_forecast], {**before, **after}, as_of)
    assert with_future == fit_calibration(past, before, as_of)


def test_too_few_windows_leave_the_band_unchanged() -> None:
    as_of = date(2026, 6, 30)
    past = [_past(as_of - timedelta(days=7 * k), width=1_000) for k in range(1, MIN_WINDOWS)]
    actual = _actual(as_of - timedelta(days=40), 41, wiggle=3_000)
    cal = fit_calibration(past, actual, as_of)
    assert all(b.scale is None for b in cal.buckets)
    assert cal.scale(5) == 1


def test_calibration_round_trips_through_json() -> None:
    as_of = date(2026, 6, 30)
    past = [_past(as_of - timedelta(days=7 * k), width=1_000) for k in range(1, 9)]
    cal = fit_calibration(past, _actual(as_of - timedelta(days=80), 81, 3_000), as_of)
    assert from_jsonable(to_jsonable(cal)) == cal


def _scaled(scale: Fraction) -> Calibration:
    past = [_past(AS_OF - timedelta(days=7 * k), width=1_000, horizon=90) for k in range(1, 9)]
    cal = fit_calibration(past, _actual(AS_OF - timedelta(days=90), 91, 3_000), AS_OF)
    buckets = tuple(type(b)(b.first_day, b.last_day, b.windows, b.points, scale, b.raw_coverage)
                    for b in cal.buckets)  # fmt: skip
    return Calibration(cal.version, cal.as_of, buckets)


def test_applying_a_scale_is_shift_equivariant_and_keeps_the_median() -> None:
    rng = np.random.default_rng(7)
    balances = rng.integers(-50_000, 50_000, size=(101, 31)).astype(np.int64)
    cal = _scaled(Fraction(7, 4))
    medians = quantile_minor(balances, Fraction(1, 2))
    out = apply_calibration(balances, medians, cal)
    shifted = apply_calibration(balances + 12_345, medians + 12_345, cal)
    assert np.array_equal(shifted, out + 12_345)
    assert np.array_equal(quantile_minor(out, Fraction(1, 2))[1:], medians[1:])
    assert np.array_equal(out[:, 0], balances[:, 0])  # today is untouched


def test_calibrated_forecast_is_deterministic_and_wider() -> None:
    inputs = make_inputs()
    cal = _scaled(Fraction(2))
    raw = build_forecast(inputs)
    a = build_forecast(inputs, calibration=cal)
    b = build_forecast(inputs, calibration=cal)
    assert a == b
    assert a.p50 == raw.p50
    assert all(a.p90[t] - a.p10[t] >= raw.p90[t] - raw.p10[t] for t in range(1, len(a.p50)))
    assert raw.inputs_hash == content_hash(inputs)  # unchanged when nothing else applies
    assert a.inputs_hash != raw.inputs_hash


# ---------------------------------------------------------------- prior


def test_uk_prior_comes_from_the_ons_table() -> None:
    assert UK_PRIOR.currency == "GBP"
    assert "ONS" in UK_PRIOR.source
    # irregular categories £100.80 a week; comparison £676.60 − £118.40 − £94.10 − £100.80
    assert UK_PRIOR.irregular_daily_minor == Fraction(10_080, 7)
    assert UK_PRIOR.comparison_daily_minor == Fraction(36_330, 7)


def test_prior_weight_fades_as_history_grows() -> None:
    weights = [prior_weight(UK_PRIOR, d) for d in (30, 90, 180, 365)]
    assert weights == sorted(weights, reverse=True)
    assert prior_weight(UK_PRIOR, 0) == 1
    assert prior_weight(UK_PRIOR, UK_PRIOR.strength_days) == Fraction(1, 2)


def test_household_scale_is_clamped() -> None:
    lo, hi = UK_PRIOR.scale_bounds
    assert household_scale(UK_PRIOR, Fraction(0)) == lo
    assert household_scale(UK_PRIOR, UK_PRIOR.comparison_daily_minor) == 1
    assert household_scale(UK_PRIOR, UK_PRIOR.comparison_daily_minor * 10) == hi


def _mean_one_off(inputs: ForecastInputs, with_prior: bool) -> float:
    prep = prepare(inputs, UK_PRIOR if with_prior else None)
    return float(prep.one_offs.sum(axis=1).mean())


def test_prior_adds_irregular_cost_and_matters_less_with_more_history() -> None:
    short = make_inputs(discretionary_history=history(days=60), n_paths=400)
    long = make_inputs(discretionary_history=history(days=365), n_paths=400)
    gap_short = _mean_one_off(short, False) - _mean_one_off(short, True)
    gap_long = _mean_one_off(long, False) - _mean_one_off(long, True)
    assert gap_short > 0  # the prior adds expected cost
    assert gap_long > 0
    assert gap_short > gap_long


def test_prior_must_match_the_forecast_currency() -> None:
    with pytest.raises(ValueError, match="prior is for GBP"):
        prepare(make_inputs(currency="EUR"), UK_PRIOR)


def test_forecast_without_prior_is_unchanged_by_the_extra_seed_stream() -> None:
    inputs = make_inputs()
    assert build_forecast(inputs) == build_forecast(inputs, prior=None, calibration=None)


# ---------------------------------------------------------------- MASE and calibrated backtest


def test_backtest_reports_mase_and_calibrates_only_from_the_past() -> None:
    start = date(2026, 1, 1)
    bal = 300_000
    hist: dict[date, int] = {}
    d = start
    while d <= date(2026, 9, 30):
        bal -= 4_000 + (d.toordinal() % 9) * 700
        if d.day == 28:
            bal += 300_000
        hist[d] = bal
        d += timedelta(days=1)

    def build(origin: date) -> ForecastInputs:
        return make_inputs(
            as_of=origin,
            starting_balance_minor=hist[origin],
            known_flows=(),
            n_paths=60,
            obligations=(),
            income_streams=(),
            discretionary_history=history(origin, days=90),
        )

    origins = [date(2026, 6, 1) + timedelta(days=7 * k) for k in range(4)]
    cal_origins = [date(2026, 3, 1) + timedelta(days=7 * k) for k in range(12)]
    out = backtest(hist, origins, build, calibrate=True, calibration_origins=cal_origins)
    assert out["n_origins"] == 4
    for h in ("7", "30", "60"):
        assert out["foresight"]["mase"][h] is not None
        assert out["foresight"]["mase"][h] > 0
        assert out["baselines"]["B0"]["mase"][h] is not None
    assert len(out["per_origin"]) == 4  # calibration-only origins are not scored
    assert out["foresight"]["calibrated_origins"] >= 0
