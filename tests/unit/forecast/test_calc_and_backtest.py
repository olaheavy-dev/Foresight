from __future__ import annotations

import dataclasses
import random
from datetime import date, timedelta

import pytest

from backend.finance_core.calc import canonical_json, content_hash, recompute, record
from backend.finance_core.forecast import backtest, build_forecast
from backend.finance_core.forecast.engine import ENGINE_VERSION
from backend.finance_core.types import ForecastInputs
from tests.unit.forecast.conftest import make_inputs


def test_canonical_json_is_order_independent() -> None:
    assert canonical_json({"b": 1, "a": frozenset({3, 1})}) == canonical_json(
        {"a": frozenset({1, 3}), "b": 1}
    )


def test_fifty_random_calculations_recompute_identically() -> None:
    rng = random.Random(7)  # noqa: S311 - test data, not security
    for _ in range(50):
        inputs = make_inputs(
            n_paths=10,
            horizon_days=rng.randint(20, 60),
            seed=rng.randint(0, 10**6),
            buffer_minor=rng.choice([None, 30000, 50000]),
        )
        calc = record("forecast", inputs, {"scope": "mine"}, build_forecast(inputs), ENGINE_VERSION)
        assert calc.id.startswith("calc_")
        fresh, same = recompute(calc, inputs, build_forecast)
        assert same
        assert fresh.id == calc.id


def test_recompute_refuses_other_inputs(inputs: ForecastInputs) -> None:
    calc = record("forecast", inputs, {}, build_forecast(inputs), ENGINE_VERSION)
    with pytest.raises(ValueError, match="do not match"):
        recompute(calc, dataclasses.replace(inputs, seed=99), build_forecast)


def test_calc_id_depends_on_question_not_result(inputs: ForecastInputs) -> None:
    a = record("forecast", inputs, {}, {"x": 1}, ENGINE_VERSION)
    b = record("forecast", inputs, {}, {"x": 2}, ENGINE_VERSION)
    assert a.id == b.id
    assert a.inputs_hash == content_hash(inputs)


def test_backtest_returns_scored_metrics_for_foresight_and_baselines() -> None:
    # A synthetic "actual" history: pay on the 28th, steady spend; enough days for 3 origins.
    start, end = date(2026, 4, 1), date(2026, 10, 12)
    history: dict[date, int] = {}
    bal = 150000
    d = start
    while d <= end:
        bal -= 2500
        if d.day == 28:
            bal += 300000
        if d.day == 1:
            bal -= 125000
        history[d] = bal
        d += timedelta(days=1)

    def build(origin: date) -> ForecastInputs:
        return make_inputs(
            as_of=origin,
            starting_balance_minor=history[origin],
            known_flows=(),
            n_paths=40,
            obligations=(),
            income_streams=(),
        )

    origins = [date(2026, 7, 1), date(2026, 7, 31), date(2026, 8, 10)]
    out = backtest(history, origins, build)
    assert out["n_origins"] == 3
    assert set(out["baselines"]) == {"B0", "B1", "B2", "B3"}
    for h in ("7", "30", "60"):
        assert out["foresight"]["mae_minor"][h] is not None
        assert out["baselines"]["B1"]["mae_minor"][h] is not None
    assert 0.0 <= out["foresight"]["coverage_p10_p90"] <= 1.0
    assert set(out["skill_vs_B1"]) == {"7", "30", "60"}
