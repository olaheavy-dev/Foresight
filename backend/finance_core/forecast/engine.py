"""Daily cash-flow forecast (docs/07 §6): known-flow calendar, block-bootstrap everyday spend, a
compound process for one-off expenses and a monthly model for irregular income.

Sources of uncertainty, each estimated from the user's own history:
- everyday discretionary spend: stationary block bootstrap of the last W = 90 days (§6.2), with
  one-off expenses removed so a single large purchase in the window doesn't set the level;
- one-off expenses (≥ 3× their category's median, §4.6): arrivals at their long-run rate over the
  whole lookback (up to 365 days), sizes drawn from the observed one-offs, so the forecast carries
  the chance of a large unplanned bill instead of assuming none (or one in every window);
- irregular income (§4.5): each calendar month's total drawn from the observed monthly totals
  (months with nothing count as zero) and landed on a uniformly random day of that month;
- irregular expenses not yet seen (§6.2b, engine v1.3): an optional population prior (national
  household-spending statistics) blended with the observed one-off rate, weighted towards the
  prior for short histories and towards the user's own data as it grows.

Optionally (§6.8a, engine v1.3) the spread of the paths is rescaled about the daily median by a
`Calibration` fitted from the engine's own earlier forecasts for this user, so the P10–P90 band
covers what it claims to (forecast/calibration.py).

All arithmetic is deterministic for a given ForecastInputs (including the seed): the same inputs
always produce byte-identical results and the same inputs_hash. Amounts are integer minor units,
and quantiles are computed exactly in integers (§6.4: linear interpolation, halves rounded up),
so adding a constant to every path moves every quantile by exactly that constant.
"""

from __future__ import annotations

import calendar as _cal
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction

import numpy as np
import numpy.typing as npt

from backend.finance_core.calc import content_hash
from backend.finance_core.calendar import obligation_dates, paydays_between
from backend.finance_core.forecast.calibration import (
    Calibration,
    apply_calibration,
)
from backend.finance_core.forecast.calibration import (
    to_jsonable as calibration_json,
)
from backend.finance_core.forecast.prior import (
    IrregularPrior,
    household_scale,
    prior_weight,
)
from backend.finance_core.forecast.prior import (
    to_jsonable as prior_json,
)
from backend.finance_core.types import (
    Cadence,
    FlowKind,
    ForecastInputs,
    ForecastResult,
    PayCycleLow,
    Quantiles,
)

ENGINE_VERSION = "fc-1.3.0"
HISTORY_WINDOW_DAYS = 90  # W in docs/07 §6.1: the everyday-spend bootstrap pool
LOOKBACK_DAYS = 365  # one-off expense rate and sizes are estimated over up to a year
MIN_LOOKBACK_DAYS = 90  # a short history still spreads its one-offs over at least 90 days
ONE_OFF_MULTIPLE = 3  # a row ≥ 3× its category median is a one-off (docs/07 §4.6, 00 §13)
MIN_CATEGORY_ROWS = 3  # a category needs this many rows before anything in it is a one-off
# Rows of these kinds only move money between tracked accounts (or settle a tracked card), so
# they never enter the history; every other outflow that isn't a scheduled obligation does.
NOT_UNSCHEDULED = frozenset({FlowKind.TRANSFER_OWN, FlowKind.CARD_SETTLEMENT})


def is_unscheduled_outflow(amount_minor: int, flow_kind: FlowKind, recurring: bool) -> bool:
    """Whether a ledger row belongs in ForecastInputs.discretionary_history (docs/07 §6.1).

    Unscheduled outflows are everything that leaves the cash balance without a schedule:
    everyday spending, fees and betting, and also ad-hoc savings transfers, extra family support,
    tax payments and payments to untracked accounts. Leaving the last group out made the forecast
    too optimistic whenever a user moves surplus money by hand."""
    return amount_minor < 0 and not recurring and flow_kind not in NOT_UNSCHEDULED


BLOCK_P = 1.0 / 7.0  # geometric block length parameter (mean 7 days)
PARAMETER_UNCERTAINTY = True  # draw rates from their posterior per path (see _bootstrap)
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
    one_offs: IntArray  # (n_paths, H + 1) one-off expenses (≤ 0)
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
        for d in paydays_between(stream.payday_rule, start, end, inputs.holidays):
            flows.append(Flow(index[d], stream.amount_minor, stream.source, stream.key))
            pays.add(d)
    for ob in inputs.obligations:
        for d in obligation_dates(ob, start, end, inputs.holidays):
            flows.append(Flow(index[d], ob.amount_minor, ob.label))
    for kf in inputs.known_flows:
        if kf.on in index and kf.on > inputs.as_of:
            flows.append(Flow(index[kf.on], kf.amount_minor, kf.label))
    flows.sort(key=lambda f: (f.day, f.label, f.amount_minor))
    return flows, sorted(pays)


@dataclass(frozen=True)
class SpendHistory:
    """The discretionary history split into everyday spend and one-off expenses."""

    everyday: tuple[tuple[date, str, int], ...]  # non-one-off rows in the last W days
    one_off_amounts: tuple[int, ...]  # one-off rows over the lookback (≤ 0)
    lookback_days: int  # days the history covers (at least MIN_LOOKBACK_DAYS)
    window_start: date  # first day of the everyday-spend pool


def split_history(inputs: ForecastInputs) -> SpendHistory:
    """Separate one-off expenses (≥ 3× the category median over the lookback) from everyday spend.

    Callers pass every discretionary, non-recurring outflow they have for up to LOOKBACK_DAYS; the
    engine makes the one-off decision itself so every caller gets the same split.
    """
    start = inputs.as_of - timedelta(days=LOOKBACK_DAYS - 1)
    rows = [r for r in inputs.discretionary_history if start <= r[0] <= inputs.as_of and r[2] < 0]
    by_category: dict[str, list[int]] = defaultdict(list)
    for _d, category, amount in rows:
        by_category[category].append(-amount)
    medians = {
        k: statistics.median(v) for k, v in by_category.items() if len(v) >= MIN_CATEGORY_ROWS
    }
    # A category too rare to have its own median (a tax bill, a one-time fee) is judged against
    # the median outflow across all categories, so a single large rare payment is still a one-off.
    overall = statistics.median(-r[2] for r in rows) if rows else 0

    def one_off(category: str, amount: int) -> bool:
        return -amount >= ONE_OFF_MULTIPLE * medians.get(category, overall)

    first = min((r[0] for r in rows), default=inputs.as_of)
    # the pool never reaches back before the history starts: days before it are unknown, not
    # days without spending
    window_start = max(first, inputs.as_of - timedelta(days=HISTORY_WINDOW_DAYS - 1))
    everyday = tuple(r for r in rows if r[0] >= window_start and not one_off(r[1], r[2]))
    one_offs = tuple(sorted(r[2] for r in rows if one_off(r[1], r[2])))
    lookback = max(MIN_LOOKBACK_DAYS, (inputs.as_of - first).days + 1)
    return SpendHistory(everyday, one_offs, lookback, window_start)


def _history_matrix(inputs: ForecastInputs, history: SpendHistory) -> tuple[IntArray, list[date]]:
    """Daily everyday-spend totals for the pool's days ending at as_of (0 on no-spend days)."""
    first = history.window_start
    n = (inputs.as_of - first).days + 1
    days = [first + timedelta(days=i) for i in range(n)]
    totals = np.zeros(n, dtype=np.int64)
    for d, _category, amount in history.everyday:
        if first <= d <= inputs.as_of:
            totals[(d - first).days] += amount
    return totals, days


def _historical_paydays(inputs: ForecastInputs, start: date, end: date) -> set[date]:
    out: set[date] = set()
    for stream in inputs.income_streams:
        if stream.payday_rule is not None and stream.cadence is not Cadence.IRREGULAR:
            out.update(paydays_between(stream.payday_rule, start, end, inputs.holidays))
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
    history: SpendHistory,
    dates: Sequence[date],
    horizon_paydays: Sequence[date],
    rng: np.random.Generator,
) -> IntArray:
    hist, hist_days = _history_matrix(inputs, history)
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
    block_p = BLOCK_P
    for p in range(n):
        # Bayesian bootstrap: each path first re-weights the history days (Dirichlet(1, …, 1)),
        # so the spread includes the uncertainty in the spending rate a short history implies,
        # not only day-to-day noise around the observed average (docs/07 §6.2).
        weights = rng.gamma(1.0, size=w) if PARAMETER_UNCERTAINTY else np.ones(w)
        t = 1
        while t <= horizon:
            length = int(rng.geometric(block_p))
            off = target_offsets[t]
            candidates = by_offset[off] if off is not None and by_offset[off] else None
            if candidates is None:
                candidates = by_weekday[dates[t].weekday()] or list(range(w))
            cum = np.cumsum(weights[candidates])
            pick = int(np.searchsorted(cum, rng.random() * cum[-1], side="right"))
            s = candidates[min(pick, len(candidates) - 1)]
            for k in range(length):
                if t + k > horizon:
                    break
                out[p, t + k] = hist[(s + k) % w]
            t += length
    return out


def _one_off_expenses(
    history: SpendHistory,
    n_paths: int,
    horizon: int,
    rng: np.random.Generator,
    rate_factor: float = 1.0,
) -> IntArray:
    """One-off expenses as a compound process: on each day a one-off arrives with probability
    (one-offs seen) / (days of history), its size drawn from the one-offs seen. `rate_factor`
    (1 − prior weight, §6.2b) leaves room for the population prior's share."""
    out = np.zeros((n_paths, horizon + 1), dtype=np.int64)
    amounts = history.one_off_amounts
    if not amounts or horizon == 0:
        return out
    values = np.asarray(amounts, dtype=np.int64)
    if PARAMETER_UNCERTAINTY:
        # Posterior predictive rather than plug-in: each path draws its own rate from the
        # Gamma(n + ½, days) posterior of a Poisson rate (Jeffreys prior) and re-weights the
        # observed sizes (Bayesian bootstrap), so few observed one-offs mean a wider spread.
        rates = rate_factor * rng.gamma(
            len(amounts) + 0.5, 1.0 / history.lookback_days, size=n_paths
        )
        size_w = rng.gamma(1.0, size=(n_paths, len(amounts)))
        cum = np.cumsum(size_w, axis=1)
        u = rng.random((n_paths, horizon)) * cum[:, -1:]
        picks = np.minimum(
            np.array([np.searchsorted(cum[p], u[p], side="right") for p in range(n_paths)]),
            len(amounts) - 1,
        )
    else:
        rates = np.full(n_paths, rate_factor * len(amounts) / history.lookback_days)
        picks = rng.integers(0, len(amounts), size=(n_paths, horizon))
    arrivals = rng.random((n_paths, horizon)) < np.minimum(rates, 1.0)[:, None]
    out[:, 1:] = np.where(arrivals, values[picks], 0)
    return out


def everyday_daily_minor(history: SpendHistory, as_of: date) -> Fraction:
    """Average everyday (non-one-off) unscheduled outflow per day over the bootstrap pool, ≥ 0."""
    days = (as_of - history.window_start).days + 1
    total = -sum(a for _d, _c, a in history.everyday)
    return Fraction(max(0, total), max(1, days))


@dataclass(frozen=True)
class PriorTerms:
    """How the irregular-expense prior enters one forecast (recorded for the evidence trail)."""

    weight: Fraction  # w = strength / (history days + strength)
    household_scale: Fraction  # r
    daily_cost_minor: Fraction  # w · r · prior daily cost: the prior's share of one-off cost


def prior_terms(
    prior: IrregularPrior | None, history: SpendHistory, as_of: date
) -> PriorTerms | None:
    if prior is None:
        return None
    w = prior_weight(prior, history.lookback_days)
    r = household_scale(prior, everyday_daily_minor(history, as_of))
    return PriorTerms(w, r, w * r * prior.irregular_daily_minor)


def _prior_irregular(
    terms: PriorTerms | None,
    prior: IrregularPrior | None,
    n_paths: int,
    horizon: int,
    rng: np.random.Generator,
) -> IntArray:
    """The prior's share of irregular expenses as a compound process: a lump arrives on each day
    with probability 1 / interval, its size exponential with mean (daily cost × interval), so the
    expected cost per day is the prior's share and single lumps can be large."""
    out = np.zeros((n_paths, horizon + 1), dtype=np.int64)
    if terms is None or prior is None or horizon == 0 or terms.daily_cost_minor <= 0:
        return out
    interval = prior.event_interval_days
    mean_size = float(terms.daily_cost_minor * interval)
    arrivals = rng.random((n_paths, horizon)) < 1.0 / interval
    sizes = np.rint(rng.exponential(mean_size, size=(n_paths, horizon))).astype(np.int64)
    out[:, 1:] = np.where(arrivals, -sizes, 0)
    return out


def _irregular_income(
    inputs: ForecastInputs, dates: Sequence[date], rng: np.random.Generator
) -> IntArray:
    """Irregular income (docs/07 §4.5): for every calendar month the horizon touches, draw that
    month's total from the stream's observed monthly totals and land it on a uniformly random day
    of the month. Days on or before as_of are dropped, so a part-elapsed month contributes in
    proportion to the days left."""
    n, horizon = inputs.n_paths, len(dates) - 1
    out = np.zeros((n, horizon + 1), dtype=np.int64)
    months = sorted({(d.year, d.month) for d in dates[1:]})
    for stream in inputs.income_streams:
        totals = stream.irregular_amounts_minor
        if stream.cadence is not Cadence.IRREGULAR or not totals:
            continue
        values = np.asarray(totals, dtype=np.int64)
        for y, m in months:
            length = _cal.monthrange(y, m)[1]
            drawn = values[rng.integers(0, len(values), size=n)]
            day = rng.integers(1, length + 1, size=n)
            offset = np.array([(date(y, m, int(d)) - inputs.as_of).days for d in day])
            inside = (offset >= 1) & (offset <= horizon)
            rows = np.nonzero(inside)[0]
            np.add.at(out, (rows, offset[inside]), drawn[inside])
    return out


def prepare(inputs: ForecastInputs, prior: IrregularPrior | None = None) -> Prepared:
    """Expand the calendar and draw all randomness for an input set (seeded)."""
    if inputs.n_paths < 1 or inputs.horizon_days < 1:
        raise ValueError("n_paths and horizon_days must be positive")
    if prior is not None and prior.currency != inputs.currency:
        raise ValueError(f"prior is for {prior.currency}, forecast is in {inputs.currency}")
    dates = _horizon_dates(inputs.as_of, inputs.horizon_days)
    flows, pays = _known_flows(inputs, dates)
    history = split_history(inputs)
    terms = prior_terms(prior, history, inputs.as_of)
    # Children are indexed, so adding the fourth stream leaves the first three draws unchanged.
    disc_seed, income_seed, one_off_seed, prior_seed = np.random.SeedSequence(inputs.seed).spawn(4)
    discretionary = _bootstrap(inputs, history, dates, pays, np.random.default_rng(disc_seed))
    irregular = _irregular_income(inputs, dates, np.random.default_rng(income_seed))
    one_offs = _one_off_expenses(
        history,
        inputs.n_paths,
        inputs.horizon_days,
        np.random.default_rng(one_off_seed),
        rate_factor=1.0 if terms is None else float(1 - terms.weight),
    ) + _prior_irregular(
        terms, prior, inputs.n_paths, inputs.horizon_days, np.random.default_rng(prior_seed)
    )
    return Prepared(
        inputs=inputs,
        dates=dates,
        flows=tuple(flows),
        paydays=tuple(pays),
        discretionary=discretionary,
        one_offs=one_offs,
        irregular_income=irregular,
        relative=inputs.starting_balance_provenance == "relative",
    )


def flows_vector(flows: Sequence[Flow], length: int) -> IntArray:
    vec = np.zeros(length, dtype=np.int64)
    for f in flows:
        vec[f.day] += f.amount_minor
    return vec


def balance_paths(prep: Prepared, flows: Sequence[Flow]) -> IntArray:
    """balance[p, t] = B0 + Σ_{s≤t}(known flows + irregular income + everyday spend + one-offs)."""
    start = 0 if prep.relative else prep.inputs.starting_balance_minor
    daily = flows_vector(flows, len(prep.dates))[None, :] + prep.discretionary
    daily = daily + prep.irregular_income + prep.one_offs
    return np.asarray(start + np.cumsum(daily, axis=1), dtype=np.int64)


QUANTILES = {"p10": Fraction(1, 10), "p50": Fraction(1, 2), "p90": Fraction(9, 10)}


def quantile_minor(values: IntArray, q: Fraction) -> IntArray:
    """Exact linear-interpolation quantile along axis 0 (numpy's "linear" method), rounded to a
    whole minor unit with halves rounded up, using integer arithmetic only.

    Floating-point interpolation followed by round-half-even made quantiles move by ±1 minor unit
    when every path was shifted by a constant; this is exactly shift-equivariant."""
    n = values.shape[0]
    h = (n - 1) * q
    j = h.numerator // h.denominator
    g = h - j  # interpolation weight in [0, 1)
    ordered = np.sort(values, axis=0)
    lo = ordered[j]
    hi = ordered[min(j + 1, n - 1)]
    num = lo * g.denominator + (hi - lo) * g.numerator  # value × denominator, exact
    return np.asarray(np.floor_divide(2 * num + g.denominator, 2 * g.denominator), dtype=np.int64)


def _quantiles(values: IntArray) -> Quantiles:
    return Quantiles(*(int(quantile_minor(values, q)) for q in QUANTILES.values()))


def _series(values: IntArray, q: Fraction) -> tuple[int, ...]:
    return tuple(int(v) for v in quantile_minor(values, q))


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
                low=_quantiles(mins),
                low_date=_modal_date(prep.dates, window.argmin(axis=1), lo),
                chance_below_buffer=chance,
            )
        )
        lo = index[pd]
    return tuple(out)


def _lowest_balance(
    dates: Sequence[date], balances: IntArray, cycles: Sequence[PayCycleLow]
) -> tuple[int, date]:
    """The headline "lowest balance": the lowest of the pay-cycle lows (P50 of the path-wise
    minimum within each cycle, docs/07 §6.5), so the summary always equals one of the lows the
    user sees. Ties go to the earliest cycle. Without a complete pay cycle in the horizon (no
    income detected), the whole horizon after today is treated as one window.

    Taking the P50 of the path-wise minimum over the whole horizon instead mixes cycles: each
    path contributes its worst cycle, so the median sits below every cycle's own low while
    sharing its modal date, and the two figures contradict each other on screen."""
    if cycles:
        lowest = min(cycles, key=lambda c: c.low.p50)
        return lowest.low.p50, lowest.low_date
    future = balances[:, 1:] if balances.shape[1] > 1 else balances
    offset = 1 if balances.shape[1] > 1 else 0
    return (
        int(quantile_minor(future.min(axis=1), QUANTILES["p50"])),
        _modal_date(dates, future.argmin(axis=1), offset),
    )


def summarise(
    prep: Prepared,
    balances: IntArray,
    inputs_hash: str,
    cycle_paydays: Sequence[date] | None = None,
) -> ForecastResult:
    dates = prep.dates
    cycles = pay_cycle_lows(
        prep, balances, prep.paydays if cycle_paydays is None else cycle_paydays
    )
    min_p50, min_date = _lowest_balance(dates, balances, cycles)
    return ForecastResult(
        as_of=prep.inputs.as_of,
        currency=prep.inputs.currency,
        horizon_days=prep.inputs.horizon_days,
        dates=dates,
        p10=_series(balances, QUANTILES["p10"]),
        p50=_series(balances, QUANTILES["p50"]),
        p90=_series(balances, QUANTILES["p90"]),
        pay_cycles=cycles,
        min_balance_p50_minor=min_p50,
        min_balance_date=min_date,
        buffer_minor=None if prep.relative else prep.inputs.buffer_minor,
        n_paths=prep.inputs.n_paths,
        seed=prep.inputs.seed,
        inputs_hash=inputs_hash,
        engine_version=ENGINE_VERSION,
    )


def calibrate_paths(balances: IntArray, calibration: Calibration | None) -> IntArray:
    """Rescale the paths' spread about each day's exact median (forecast/calibration.py)."""
    if calibration is None or not calibration.calibrated:
        return balances
    medians = quantile_minor(balances, QUANTILES["p50"])
    return apply_calibration(balances, medians, calibration)


def forecast_hash(
    inputs: ForecastInputs,
    prior: IrregularPrior | None = None,
    calibration: Calibration | None = None,
    extra: dict[str, object] | None = None,
) -> str:
    """inputs_hash: the inputs alone when nothing else shapes the result (unchanged from v1.2),
    otherwise the inputs together with the prior, the calibration and any scenario."""
    if prior is None and calibration is None and extra is None:
        return content_hash(inputs)
    parts: dict[str, object] = {"inputs": inputs, **(extra or {})}
    if prior is not None:
        parts["prior"] = prior_json(prior)
    if calibration is not None:
        parts["calibration"] = calibration_json(calibration)
    return content_hash(parts)


def build_forecast(
    inputs: ForecastInputs,
    *,
    prior: IrregularPrior | None = None,
    calibration: Calibration | None = None,
) -> ForecastResult:
    """Forecast the daily balance distribution for the horizon (docs/07 §6.4). `prior` adds the
    population prior for irregular expenses (§6.2b); `calibration` rescales the band (§6.8a)."""
    prep = prepare(inputs, prior)
    balances = calibrate_paths(balance_paths(prep, prep.flows), calibration)
    return summarise(prep, balances, forecast_hash(inputs, prior, calibration))
