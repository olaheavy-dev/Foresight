"""Daily cash-flow forecast: known-flow calendar + block-bootstrap discretionary spend (docs/07 §6).

All arithmetic is deterministic for a given ForecastInputs (including the seed): the same inputs
always produce byte-identical results and the same inputs_hash. Amounts are integer minor units.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import numpy.typing as npt

from backend.finance_core.calc import content_hash
from backend.finance_core.forecast._calendar import obligation_dates, paydays
from backend.finance_core.types import (
    Cadence,
    ForecastInputs,
    ForecastResult,
    PayCycleLow,
    Quantiles,
)

ENGINE_VERSION = "fc-1.0.0"
HISTORY_WINDOW_DAYS = 90  # W in docs/07 §6.1
BLOCK_P = 1.0 / 7.0  # geometric block length parameter (mean 7 days)
PAYDAY_ALIGN_DAYS = 3  # payday and the next two days draw from post-payday history

IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class Flow:
    """A known flow on a horizon day (index into the date axis)."""

    day: int
    amount_minor: int
    label: str
    income_key: str | None = None  # set for income occurrences (used by income_delay)


@dataclass(frozen=True)
class Prepared:
    """Everything random or calendar-derived, computed once so that simulations reuse exactly
    the same draws (common random numbers)."""

    inputs: ForecastInputs
    dates: tuple[date, ...]  # as_of .. as_of + H
    flows: tuple[Flow, ...]  # baseline known flows (income, obligations, one-offs)
    paydays: tuple[date, ...]  # baseline paydays in the horizon (union of streams with rules)
    discretionary: IntArray  # (n_paths, H + 1) daily discretionary amounts (≤ 0); column 0 = 0
    irregular_income: IntArray  # (n_paths, H + 1) daily irregular income (≥ 0)
    relative: bool


def _horizon_dates(as_of: date, horizon: int) -> tuple[date, ...]:
    return tuple(as_of + timedelta(days=i) for i in range(horizon + 1))


def _known_flows(inputs: ForecastInputs, dates: Sequence[date]) -> tuple[list[Flow], list[date]]:
    start, end = dates[1] if len(dates) > 1 else dates[0], dates[-1]
    index = {d: i for i, d in enumerate(dates)}
    flows: list[Flow] = []
    pays: set[date] = set()
    for stream in inputs.income_streams:
        if stream.payday_rule is None or stream.cadence is Cadence.IRREGULAR:
            continue
        for d in paydays(stream.payday_rule, start, end, inputs.holidays):
            flows.append(Flow(index[d], stream.amount_minor, stream.source, stream.key))
            pays.add(d)
    for ob in inputs.obligations:
        for d in obligation_dates(ob, start, end):
            flows.append(Flow(index[d], ob.amount_minor, ob.label))
    for kf in inputs.known_flows:
        if kf.on in index and kf.on > inputs.as_of:
            flows.append(Flow(index[kf.on], kf.amount_minor, kf.label))
    flows.sort(key=lambda f: (f.day, f.label, f.amount_minor))
    return flows, sorted(pays)


def _history_matrix(inputs: ForecastInputs) -> tuple[IntArray, list[date]]:
    """Daily discretionary totals for the W days ending at as_of (0 on no-spend days)."""
    first = inputs.as_of - timedelta(days=HISTORY_WINDOW_DAYS - 1)
    days = [first + timedelta(days=i) for i in range(HISTORY_WINDOW_DAYS)]
    totals = np.zeros(HISTORY_WINDOW_DAYS, dtype=np.int64)
    for d, _category, amount in inputs.discretionary_history:
        if first <= d <= inputs.as_of:
            totals[(d - first).days] += amount
    return totals, days


def _historical_paydays(inputs: ForecastInputs, start: date, end: date) -> set[date]:
    out: set[date] = set()
    for stream in inputs.income_streams:
        if stream.payday_rule is not None and stream.cadence is not Cadence.IRREGULAR:
            out.update(paydays(stream.payday_rule, start, end, inputs.holidays))
    return out


def _post_payday_offsets(days: Sequence[date], pays: set[date]) -> list[int | None]:
    """For each day, how many days after the most recent payday it is (0..2), else None."""
    out: list[int | None] = []
    for d in days:
        offset = None
        for k in range(PAYDAY_ALIGN_DAYS):
            if d - timedelta(days=k) in pays:
                offset = k
                break
        out.append(offset)
    return out


def _bootstrap(
    inputs: ForecastInputs,
    dates: Sequence[date],
    horizon_paydays: Sequence[date],
    rng: np.random.Generator,
) -> IntArray:
    hist, hist_days = _history_matrix(inputs)
    n, horizon = inputs.n_paths, len(dates) - 1
    out = np.zeros((n, horizon + 1), dtype=np.int64)
    if not hist.any() or horizon == 0:
        return out
    by_weekday: dict[int, list[int]] = {wd: [] for wd in range(7)}
    for i, d in enumerate(hist_days):
        by_weekday[d.weekday()].append(i)
    hist_pays = _historical_paydays(inputs, hist_days[0], hist_days[-1])
    hist_offsets = _post_payday_offsets(hist_days, hist_pays)
    by_offset: dict[int, list[int]] = {k: [] for k in range(PAYDAY_ALIGN_DAYS)}
    for i, off in enumerate(hist_offsets):
        if off is not None:
            by_offset[off].append(i)
    target_offsets = _post_payday_offsets(dates, set(horizon_paydays))
    w = len(hist)
    for p in range(n):
        t = 1
        while t <= horizon:
            length = int(rng.geometric(BLOCK_P))
            off = target_offsets[t]
            candidates = by_offset[off] if off is not None and by_offset[off] else None
            if candidates is None:
                candidates = by_weekday[dates[t].weekday()] or list(range(w))
            s = candidates[int(rng.integers(len(candidates)))]
            for k in range(length):
                if t + k > horizon:
                    break
                out[p, t + k] = hist[(s + k) % w]
            t += length
    return out


def _irregular_income(inputs: ForecastInputs, horizon: int, rng: np.random.Generator) -> IntArray:
    out = np.zeros((inputs.n_paths, horizon + 1), dtype=np.int64)
    for stream in inputs.income_streams:
        amounts = stream.irregular_amounts_minor
        if stream.cadence is not Cadence.IRREGULAR or not amounts:
            continue
        rate = min(1.0, len(amounts) / HISTORY_WINDOW_DAYS)
        arrivals = rng.random((inputs.n_paths, horizon)) < rate
        picks = rng.integers(0, len(amounts), size=(inputs.n_paths, horizon))
        values = np.asarray(amounts, dtype=np.int64)[picks]
        out[:, 1:] += np.where(arrivals, values, 0)
    return out


def prepare(inputs: ForecastInputs) -> Prepared:
    """Expand the calendar and draw all randomness for an input set (seeded)."""
    if inputs.n_paths < 1 or inputs.horizon_days < 1:
        raise ValueError("n_paths and horizon_days must be positive")
    dates = _horizon_dates(inputs.as_of, inputs.horizon_days)
    flows, pays = _known_flows(inputs, dates)
    seq = np.random.SeedSequence(inputs.seed)
    disc_seed, income_seed = seq.spawn(2)
    discretionary = _bootstrap(inputs, dates, pays, np.random.default_rng(disc_seed))
    irregular = _irregular_income(inputs, inputs.horizon_days, np.random.default_rng(income_seed))
    return Prepared(
        inputs=inputs,
        dates=dates,
        flows=tuple(flows),
        paydays=tuple(pays),
        discretionary=discretionary,
        irregular_income=irregular,
        relative=inputs.starting_balance_provenance == "relative",
    )


def flows_vector(flows: Sequence[Flow], length: int) -> IntArray:
    vec = np.zeros(length, dtype=np.int64)
    for f in flows:
        vec[f.day] += f.amount_minor
    return vec


def balance_paths(prep: Prepared, flows: Sequence[Flow]) -> IntArray:
    """balance[p, t] = B0 + Σ_{s≤t}(known flows + irregular income + discretionary)."""
    start = 0 if prep.relative else prep.inputs.starting_balance_minor
    daily = flows_vector(flows, len(prep.dates))[None, :] + prep.discretionary
    daily = daily + prep.irregular_income
    return np.asarray(start + np.cumsum(daily, axis=1), dtype=np.int64)


def _q(values: IntArray, q: float, axis: int | None = None) -> npt.NDArray[np.float64]:
    return np.asarray(np.quantile(values, q, axis=axis, method="linear"), dtype=np.float64)


def _round(arr: npt.NDArray[np.float64]) -> tuple[int, ...]:
    return tuple(int(v) for v in np.rint(arr).astype(np.int64))


def _modal_date(dates: Sequence[date], argmins: IntArray, offset: int) -> date:
    counts = Counter(int(i) for i in argmins)
    best = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return dates[offset + best]


def pay_cycle_lows(
    prep: Prepared, balances: IntArray, cycle_paydays: Sequence[date]
) -> tuple[PayCycleLow, ...]:
    """Lowest balance before each payday: the window runs from the day after the previous
    boundary (or tomorrow) to the day before the payday."""
    buffer = prep.inputs.buffer_minor
    index = {d: i for i, d in enumerate(prep.dates)}
    out: list[PayCycleLow] = []
    lo = 1
    for pd in cycle_paydays:
        hi = index[pd] - 1
        if hi < lo:
            lo = index[pd]
            continue
        window = balances[:, lo : hi + 1]
        mins = window.min(axis=1)
        chance = (
            None if buffer is None or prep.relative else round(float(np.mean(mins < buffer)), 4)
        )
        out.append(
            PayCycleLow(
                payday=pd,
                low=Quantiles(*_round(np.array([_q(mins, 0.1), _q(mins, 0.5), _q(mins, 0.9)]))),
                low_date=_modal_date(prep.dates, window.argmin(axis=1), lo),
                chance_below_buffer=chance,
            )
        )
        lo = index[pd]
    return tuple(out)


def summarise(
    prep: Prepared,
    balances: IntArray,
    inputs_hash: str,
    cycle_paydays: Sequence[date] | None = None,
) -> ForecastResult:
    dates = prep.dates
    future = balances[:, 1:] if balances.shape[1] > 1 else balances
    path_min = future.min(axis=1)
    offset = 1 if balances.shape[1] > 1 else 0
    return ForecastResult(
        as_of=prep.inputs.as_of,
        currency=prep.inputs.currency,
        horizon_days=prep.inputs.horizon_days,
        dates=dates,
        p10=_round(_q(balances, 0.1, axis=0)),
        p50=_round(_q(balances, 0.5, axis=0)),
        p90=_round(_q(balances, 0.9, axis=0)),
        pay_cycles=pay_cycle_lows(
            prep, balances, prep.paydays if cycle_paydays is None else cycle_paydays
        ),
        min_balance_p50_minor=int(np.rint(_q(path_min, 0.5))),
        min_balance_date=_modal_date(dates, future.argmin(axis=1), offset),
        buffer_minor=None if prep.relative else prep.inputs.buffer_minor,
        n_paths=prep.inputs.n_paths,
        seed=prep.inputs.seed,
        inputs_hash=inputs_hash,
        engine_version=ENGINE_VERSION,
    )


def build_forecast(inputs: ForecastInputs) -> ForecastResult:
    """Forecast the daily balance distribution for the horizon (docs/07 §6.4)."""
    prep = prepare(inputs)
    balances = balance_paths(prep, prep.flows)
    return summarise(prep, balances, content_hash(inputs))
