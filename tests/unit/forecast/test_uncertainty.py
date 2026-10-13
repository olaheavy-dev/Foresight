"""The forecast's sources of uncertainty (docs/07 §4.5, §4.6, §6.2) and exact quantiles (§6.4)."""

from __future__ import annotations

from datetime import date, timedelta
from fractions import Fraction

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.finance_core.forecast.engine import (
    HISTORY_WINDOW_DAYS,
    QUANTILES,
    build_forecast,
    is_unscheduled_outflow,
    prepare,
    quantile_minor,
    split_history,
)
from backend.finance_core.types import Cadence, FlowKind, IncomeStream, Provenance
from tests.unit.forecast.conftest import AS_OF, history, make_inputs


@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.integers(-(10**9), 10**9), min_size=1, max_size=60),
    st.integers(-(10**7), 10**7),
    st.sampled_from(list(QUANTILES.values())),
)
def test_quantiles_move_exactly_with_a_constant_shift(
    values: list[int], c: int, q: Fraction
) -> None:
    x = np.asarray(values, dtype=np.int64)
    assert int(quantile_minor(x + c, q)) == int(quantile_minor(x, q)) + c


def test_quantiles_match_numpy_linear_interpolation() -> None:
    rng = np.random.default_rng(7)
    x = rng.integers(-500_000, 500_000, size=(500, 12), dtype=np.int64)
    for q in QUANTILES.values():
        ours = quantile_minor(x, q)
        ref = np.quantile(x, float(q), axis=0, method="linear")
        assert np.all(np.abs(ours - ref) <= 0.5 + 1e-9)


def test_a_rare_large_outflow_is_a_one_off_not_everyday_spend() -> None:
    rows = (*history(), (AS_OF - timedelta(days=3), "shopping.general", -89900))
    split = split_history(make_inputs(discretionary_history=rows))
    assert -89900 in split.one_off_amounts
    assert all(amount != -89900 for _d, _c, amount in split.everyday)


def test_one_offs_seen_over_a_year_arrive_at_their_long_run_rate() -> None:
    year = history(days=365)
    big = tuple((AS_OF - timedelta(days=60 * k + 5), "groceries", -50000) for k in range(6))
    inputs = make_inputs(discretionary_history=(*year, *big), n_paths=400, horizon_days=90)
    prep = prepare(inputs)
    split = split_history(inputs)
    assert 360 <= split.lookback_days <= 365
    assert len(split.one_off_amounts) == 6
    # six in a year ≈ 1.5 in 90 days: the mean one-off outflow is about 1.5 × £500
    mean_total = -prep.one_offs[:, 1:].sum(axis=1).mean()
    assert 45_000 < mean_total < 110_000


def test_everyday_pool_never_reaches_before_the_history_starts() -> None:
    short = history(days=40)
    split = split_history(make_inputs(discretionary_history=short))
    first = min(d for d, _c, _a in short)
    assert split.window_start == first
    assert (AS_OF - split.window_start).days < HISTORY_WINDOW_DAYS


def test_irregular_income_draws_whole_months_including_empty_ones() -> None:
    stream = IncomeStream(
        key="inc_irregular",
        source="Irregular income",
        amount_minor=100000,
        currency="GBP",
        cadence=Cadence.IRREGULAR,
        payday_rule=None,
        provenance=Provenance.DETECTED,
        irregular_amounts_minor=(0, 300000),
    )
    inputs = make_inputs(
        income_streams=(stream,), as_of=date(2026, 10, 31), horizon_days=61, n_paths=400
    )
    prep = prepare(inputs)
    monthly = [
        prep.irregular_income[:, 1:31].sum(axis=1),
        prep.irregular_income[:, 31:].sum(axis=1),
    ]
    for totals in monthly:  # November, then December
        assert set(np.unique(totals)) <= {0, 300000}
        assert 0.35 < float(np.mean(totals > 0)) < 0.65


def test_unscheduled_outflows_include_ad_hoc_savings_but_not_own_transfers() -> None:
    assert is_unscheduled_outflow(-5000, FlowKind.SPENDING, recurring=False)
    assert is_unscheduled_outflow(-200000, FlowKind.SAVINGS_INVESTMENT, recurring=False)
    assert not is_unscheduled_outflow(-40000, FlowKind.SAVINGS_INVESTMENT, recurring=True)
    assert not is_unscheduled_outflow(-10000, FlowKind.TRANSFER_OWN, recurring=False)
    assert not is_unscheduled_outflow(-10000, FlowKind.CARD_SETTLEMENT, recurring=False)
    assert not is_unscheduled_outflow(5000, FlowKind.REFUND, recurring=False)


def test_forecast_band_is_wider_with_one_offs_than_without() -> None:
    year = history(days=365)
    big = tuple((AS_OF - timedelta(days=45 * k + 3), "groceries", -60000) for k in range(8))
    plain = build_forecast(make_inputs(discretionary_history=year))
    lumpy = build_forecast(make_inputs(discretionary_history=(*year, *big)))
    assert lumpy.p50[-1] - lumpy.p10[-1] > plain.p50[-1] - plain.p10[-1]
