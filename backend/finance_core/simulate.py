"""What-if simulation on the same engine with common random numbers (docs/07 §6.5).

The scenario reuses the baseline's discretionary draws and seed, so every difference between the
baseline and the simulated result comes from the scenario's modifiers, never from randomness.

Modifiers and how each is applied:

- `one_off_outflow` / `one_off_inflow`: one fixed flow on `date`, in every path.
- `split_outflow`: `amount_minor` split into `instalments` equal flows (the remainder on the first),
  starting on `start date` (`date`), every `cadence` (weekly | fortnightly | monthly); every
  instalment must fall after `as_of` and inside the horizon, or the scenario is refused.
- `income_delay`: the stream's next `occurrences` paydays (all if None) move `days` later, then to
  the next working day; pay pushed past the horizon leaves the forecast.
- `income_change_pct`: the stream's paydays (or every stream for `all_income`) in
  [from_date, to_date] scaled by (100 + pct) / 100; −100 is a temporary loss of that income.
- `recurring_add`: a new obligation of `amount_minor` every `cadence` from `from_date`/`date`.
- `recurring_change`: the obligation `recurring_id` costs `amount_minor` (the new amount) from
  `from_date`; `recurring_cancel`: it stops from `from_date`.
- `category_cut_pct` / `category_cap`: an expected-value adjustment on the common draws. The
  category's average daily everyday spend over the bootstrap window (the same pool the engine
  samples) is reduced by `pct`%, or to `monthly_cap_minor` a month, on each day in the period, so
  the paths keep their shape and the difference is exactly the cut. A cap only ever reduces spend.
- `buffer_override`: changes the threshold for the breach chance only; the cash paths are
  identical (docs/07 §6.5).

`move_to_goal` needs goals, which are not built yet: it is rejected, never guessed.
"""

from __future__ import annotations

import calendar as _calendar
import dataclasses
from collections.abc import Iterator
from datetime import date, timedelta

from backend.finance_core.calendar import next_working_day, obligation_dates, paydays_between
from backend.finance_core.forecast.calibration import Calibration
from backend.finance_core.forecast.engine import (
    Flow,
    Prepared,
    balance_paths,
    calibrate_paths,
    forecast_hash,
    pay_cycle_lows,
    prepare,
    split_history,
    summarise,
)
from backend.finance_core.forecast.prior import IrregularPrior
from backend.finance_core.types import (
    ForecastInputs,
    RecurringObligation,
    ScenarioModifier,
    ScenarioSpec,
    SimulationResult,
)

SUPPORTED = frozenset(
    {
        "one_off_outflow",
        "one_off_inflow",
        "split_outflow",
        "income_delay",
        "income_change_pct",
        "recurring_add",
        "recurring_change",
        "recurring_cancel",
        "category_cut_pct",
        "category_cap",
        "buffer_override",
    }
)
ALL_INCOME = "all_income"
CADENCE_DAYS = {"weekly": 7, "fortnightly": 14}


# The simulator's own semantics, stored with every simulation so a change here can't be shadowed
# by an older stored result under the same key (the forecast engine keeps ENGINE_VERSION).
# sim-2 (#55): a zeroed payday stays as a zero flow, so lost income keeps its pay cycles.
SIMULATOR_VERSION = "sim-2"

# A what-if dated past the usual horizon extends it through the pay cycle its latest change falls
# in, up to 180 days (docs/00 §6: the 365-day maximum is for goals only); a change whose pay cycle
# can't close by then is refused. With no projected payday, it shows this many days instead.
SHOW_DAYS = 31
MAX_HORIZON_DAYS = 180


class ScenarioError(ValueError):
    """A scenario that cannot be simulated as specified (never guessed or silently fixed)."""


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, _calendar.monthrange(year, month)[1]))


def _series_dates(start: date, cadence: str, end: date, count: int | None = None) -> Iterator[date]:
    if cadence not in (*CADENCE_DAYS, "monthly"):
        raise ScenarioError(f"cadence must be weekly, fortnightly or monthly, not {cadence!r}")
    n = 0
    current = start
    while current <= end and (count is None or n < count):
        yield current
        n += 1
        current = (
            _add_months(start, n)
            if cadence == "monthly"
            else start + timedelta(days=CADENCE_DAYS[cadence] * n)
        )


def _in_period(d: date, mod: ScenarioModifier) -> bool:
    return (mod.from_date is None or d >= mod.from_date) and (
        mod.to_date is None or d <= mod.to_date
    )


def _obligation(inputs: ForecastInputs, key: str | None) -> RecurringObligation:
    for ob in inputs.obligations:
        if ob.key == key:
            return ob
    raise ScenarioError(f"no recurring obligation {key!r} in this forecast")


def _positive_amount(mod: ScenarioModifier) -> int:
    if mod.amount_minor is None or mod.amount_minor <= 0:
        raise ScenarioError(f"{mod.type} needs a positive amount")
    return mod.amount_minor


def _category_daily(prep: Prepared, category: str | None) -> int:
    """Average daily everyday spend in `category` over the bootstrap pool (≥ 0, minor units)."""
    if not category:
        raise ScenarioError("a category modifier needs a category")
    history = split_history(prep.inputs)
    days = (prep.inputs.as_of - history.window_start).days + 1
    total = -sum(a for _d, c, a in history.everyday if c == category)
    if total <= 0:
        raise ScenarioError(f"no recent spending in category {category!r} to change")
    return round(total / days)


def _apply(
    flows: list[Flow], mod: ScenarioModifier, prep: Prepared, index: dict[date, int]
) -> list[Flow]:
    inputs = prep.inputs
    dates = prep.dates
    in_horizon = [d for d in dates if d > inputs.as_of]
    # A period that misses the forecast entirely would change nothing: refuse it, never answer
    # "no difference" for a change that wasn't simulated.
    if mod.from_date and mod.to_date and mod.from_date > mod.to_date:
        raise ScenarioError(f"{mod.type} from_date {mod.from_date} is after to_date {mod.to_date}")
    if mod.from_date and in_horizon and mod.from_date > in_horizon[-1]:
        raise ScenarioError(f"{mod.type} from_date {mod.from_date} is outside the forecast horizon")
    if mod.to_date and mod.to_date <= inputs.as_of:
        raise ScenarioError(f"{mod.type} to_date {mod.to_date} is before the forecast starts")
    if mod.type in ("one_off_outflow", "one_off_inflow"):
        amount = _positive_amount(mod)
        if mod.date is None:
            raise ScenarioError(f"{mod.type} needs a date")
        if mod.date <= inputs.as_of or mod.date not in index:
            raise ScenarioError(f"{mod.type} date {mod.date} is outside the forecast horizon")
        sign = -1 if mod.type == "one_off_outflow" else 1
        return [*flows, Flow(index[mod.date], sign * amount, mod.label or mod.type)]
    if mod.type == "split_outflow":
        amount = _positive_amount(mod)
        start = mod.date or mod.from_date
        if start is None or not mod.instalments or mod.instalments < 1:
            raise ScenarioError("split_outflow needs a start date and at least one instalment")
        n = mod.instalments
        # Every instalment must land in the forecast: one dropped silently would show the plan
        # costing less than it does.
        if start <= inputs.as_of:
            raise ScenarioError(
                f"split_outflow first payment {start} is not after the forecast date {inputs.as_of}"
            )
        due = list(_series_dates(start, mod.cadence or "monthly", dates[-1], n))
        if len(due) < n or any(d not in index for d in due):
            raise ScenarioError(
                f"split_outflow's last payment falls after the forecast horizon; "
                f"a longer horizon_days is needed for {n} payments"
            )
        part, rest = divmod(amount, n)
        out = list(flows)
        for i, d in enumerate(due):
            out.append(Flow(index[d], -(part + (rest if i == 0 else 0)), mod.label or mod.type))
        return out
    if mod.type == "income_delay":
        if mod.income_stream_key is None or mod.days is None or mod.days <= 0:
            raise ScenarioError("income_delay needs an income stream and a positive number of days")
        targets = sorted(
            (f for f in flows if f.income_key == mod.income_stream_key), key=lambda f: f.day
        )
        if not targets:
            raise ScenarioError(f"no paydays for income stream {mod.income_stream_key!r}")
        chosen = targets if mod.occurrences is None else targets[: mod.occurrences]
        ids = {id(f) for f in chosen}
        out = []
        for f in flows:
            if id(f) not in ids:
                out.append(f)
                continue
            # Delayed pay lands on the next working day on or after the delayed date.
            new_date = next_working_day(dates[f.day] + timedelta(days=mod.days), inputs.holidays)
            if new_date in index:  # beyond the horizon: the money leaves the forecast
                out.append(dataclasses.replace(f, day=index[new_date]))
        return out
    if mod.type == "income_change_pct":
        if mod.pct is None or not -100 <= mod.pct <= 300:
            raise ScenarioError("income_change_pct needs pct between −100 and 300")
        key = mod.income_stream_key or ALL_INCOME
        hit = [f for f in flows if f.income_key and (key == ALL_INCOME or f.income_key == key)]
        if not hit:
            raise ScenarioError(f"no paydays for income stream {key!r}")
        scaled = {id(f) for f in hit if _in_period(dates[f.day], mod)}
        if mod.to_date is None or mod.to_date > dates[-1]:
            # The change runs past the forecast: a stream with no changed payday in it would be
            # shown unchanged, a partial answer (#55 review). Refuse it instead.
            changed = {f.income_key for f in hit if id(f) in scaled}
            missed = sorted({f.income_key for f in hit if f.income_key} - changed)
            if scaled and missed:
                raise ScenarioError(
                    "income_change_pct: the forecast ends before the first changed payday "
                    f"of {missed[0]!r}"
                )
        if not scaled:
            # No payday of it falls in the period: never answer "no difference" (#55 review).
            raise ScenarioError(f"income_change_pct: no {key!r} payday falls in the period")
        out = []
        for f in flows:
            if id(f) not in scaled:
                out.append(f)
                continue
            # Kept at zero (−100%, income lost) so the payday still closes its pay cycle: no
            # pay is not the same as the forecast ending (#55 review).
            out.append(dataclasses.replace(f, amount_minor=f.amount_minor * (100 + mod.pct) // 100))
        return out
    if mod.type == "recurring_add":
        amount = _positive_amount(mod)
        start = mod.from_date or mod.date
        if start is None:
            raise ScenarioError("recurring_add needs a start date")
        out = list(flows)
        for d in _series_dates(start, mod.cadence or "monthly", dates[-1]):
            if d > inputs.as_of and d in index:
                out.append(Flow(index[d], -amount, mod.label or "recurring_add"))
        return out
    if mod.type in ("recurring_change", "recurring_cancel"):
        ob = _obligation(inputs, mod.recurring_id)
        start = mod.from_date or inputs.as_of
        new_amount = -_positive_amount(mod) if mod.type == "recurring_change" else 0
        out = list(flows)
        for d in obligation_dates(ob, in_horizon[0], dates[-1], inputs.holidays):
            if d >= start and _in_period(d, mod):
                # Cancel the baseline occurrence, then add the new amount (0 when cancelled).
                out.append(Flow(index[d], new_amount - ob.amount_minor, f"{mod.type}:{ob.label}"))
        if len(out) == len(flows):
            # No payment of it falls in the period: never answer "no difference" (#55 review).
            raise ScenarioError(
                f"{mod.type}: no {ob.label} payment falls in the forecast from {start}"
            )
        return out
    if mod.type in ("category_cut_pct", "category_cap"):
        daily = _category_daily(prep, mod.category_key)
        out = list(flows)
        for d in in_horizon:
            if not _in_period(d, mod):
                continue
            if mod.type == "category_cut_pct":
                if mod.pct is None or not 0 <= mod.pct <= 100:
                    raise ScenarioError("category_cut_pct needs pct between 0 and 100")
                saving = daily * mod.pct // 100
            else:
                if mod.monthly_cap_minor is None or mod.monthly_cap_minor < 0:
                    raise ScenarioError("category_cap needs a monthly cap of zero or more")
                month_days = _calendar.monthrange(d.year, d.month)[1]
                saving = max(0, daily - mod.monthly_cap_minor // month_days)
            if saving:
                out.append(Flow(index[d], saving, f"{mod.type}:{mod.category_key}"))
        return out
    if mod.type == "buffer_override":
        return flows  # threshold only; applied in simulate()
    raise ScenarioError(f"unsupported modifier {mod.type!r}; supported: {sorted(SUPPORTED)}")


def latest_affected(inputs: ForecastInputs, spec: ScenarioSpec) -> date:
    """The latest date a what-if changes something that must sit in a reported pay-cycle low: a
    one-off's date, a split's last instalment, the first payment a recurring change or
    cancellation affects (or its last, when bounded), each income stream's first changed payday,
    a daily change's end. `as_of` when nothing is dated. A start past `MAX_HORIZON_DAYS` is
    refused before any date arithmetic."""
    as_of, cap = inputs.as_of, inputs.as_of + timedelta(days=MAX_HORIZON_DAYS)
    affected = as_of
    for mod in spec.modifiers:
        start = mod.date or mod.from_date
        # A bounded change (a `to_date` before the cap) closes the cycle of the last flow it
        # actually changes, not of its raw end date (#55 review); one ending past the cap runs
        # to the forecast's end, like an open one.
        bound = mod.to_date if mod.to_date is not None and mod.to_date < cap else None
        if mod.type in ("recurring_change", "recurring_cancel"):
            ob = next((o for o in inputs.obligations if o.key == mod.recurring_id), None)
            begin = max(start or as_of, as_of + timedelta(days=1))
            due = obligation_dates(ob, begin, cap, inputs.holidays) if ob and begin < cap else []
            start = next((d for d in due if d >= begin), start)
            if bound is not None:
                affected = max([affected, *(d for d in due if begin <= d <= bound)])
        elif mod.type == "income_change_pct":
            # Each stream's first payday on or after the change (shifted paydays can sit more
            # than a month apart), so the change shows on every stream it targets.
            begin = max(mod.from_date or as_of, as_of + timedelta(days=1))
            key = mod.income_stream_key or ALL_INCOME
            streams = [
                pays
                for stream in inputs.income_streams
                if stream.payday_rule is not None and key in (ALL_INCOME, stream.key)
                if begin < cap
                if (pays := paydays_between(stream.payday_rule, begin, cap, inputs.holidays))
            ]
            if mod.from_date is not None:
                start = max((pays[0] for pays in streams), default=start)
            if bound is not None:
                affected = max([affected, *(d for pays in streams for d in pays if d <= bound)])
        elif mod.type == "recurring_add" and bound is not None and start is not None:
            if start < cap:
                series = _series_dates(start, mod.cadence or "monthly", bound)
                affected = max([affected, *series])
        elif bound is not None:
            affected = max(affected, bound)  # a daily change (a category cut) runs to its end
        if start is None:
            continue
        if start >= cap:  # even 9999-12-31: refused before any date arithmetic
            raise ScenarioError(
                f"{mod.type} on {start} is more than {MAX_HORIZON_DAYS} days after the forecast "
                "starts"
            )
        if mod.type == "split_outflow" and mod.instalments and mod.instalments > 1:
            *_, start = _series_dates(start, mod.cadence or "monthly", cap, mod.instalments)
        affected = max(affected, start)
    return affected


def horizon_covering(inputs: ForecastInputs, spec: ScenarioSpec) -> int:
    """The horizon a what-if needs: the forecast's own, or through the first payday after its
    `latest_affected` date, so the pay cycle it lands in closes and its low is reported (docs/00
    §6, #55 review). At most `MAX_HORIZON_DAYS`; a change whose cycle can't close by then is
    refused."""
    as_of, cap = inputs.as_of, inputs.as_of + timedelta(days=MAX_HORIZON_DAYS)
    affected = latest_affected(inputs, spec)
    if affected <= as_of:
        return inputs.horizon_days  # nothing dated: the forecast's own horizon
    rules = [s.payday_rule for s in inputs.income_streams if s.payday_rule is not None]
    if not rules:  # no projected payday to close a cycle: show a month of the change
        reach = affected + timedelta(days=SHOW_DAYS)
        if reach > cap:  # a shorter window would understate it (#55 review)
            raise ScenarioError(
                f"a month after {affected} is more than {MAX_HORIZON_DAYS} days after the "
                "forecast starts"
            )
        return max(inputs.horizon_days, (reach - as_of).days)
    after = affected + timedelta(days=1)
    closing = min(
        (p for r in rules for p in paydays_between(r, after, cap, inputs.holidays)), default=None
    )
    if closing is None:
        raise ScenarioError(
            f"the pay cycle after {affected} ends more than {MAX_HORIZON_DAYS} days after the "
            "forecast starts"
        )
    return max(inputs.horizon_days, (closing - as_of).days)


def check_cycle_closes(
    inputs: ForecastInputs, spec: ScenarioSpec, result: SimulationResult
) -> None:
    """Refuse a simulated what-if whose latest affected date sits after the last payday of the
    baseline or of the simulated paths (an income delay moves paydays), so no reported low
    includes it and the verdict could call it comfortable (#55 review). Not applied without
    projected paydays, nor when nothing is dated."""
    affected = latest_affected(inputs, spec)
    if affected <= inputs.as_of or not result.baseline.pay_cycles:
        return  # nothing dated, or no projected payday at all
    for line in (result.baseline, result.simulated):
        # No simulated cycle left (a delay moved every payday out) closes nothing either.
        if not line.pay_cycles or line.pay_cycles[-1].payday <= affected:
            raise ScenarioError(
                f"the forecast ends before the pay cycle with {affected} in it closes; "
                "a later payday is needed to show it"
            )


def simulate(
    baseline_inputs: ForecastInputs,
    spec: ScenarioSpec,
    *,
    prior: IrregularPrior | None = None,
    calibration: Calibration | None = None,
) -> SimulationResult:
    """Baseline and scenario on the same draws. `prior` and `calibration` must be the ones the
    baseline forecast used, so the comparison stays like for like (docs/07 §6.2b, §6.8a)."""
    if spec.currency != baseline_inputs.currency:
        raise ScenarioError(
            f"scenario currency {spec.currency} differs from the forecast currency "
            f"{baseline_inputs.currency}; cross-currency arithmetic is not allowed"
        )
    inputs = baseline_inputs
    if spec.horizon_days is not None and spec.horizon_days != inputs.horizon_days:
        inputs = dataclasses.replace(inputs, horizon_days=spec.horizon_days)
    prep = prepare(inputs, prior)
    index = {d: i for i, d in enumerate(prep.dates)}
    flows = list(prep.flows)
    for mod in spec.modifiers:
        flows = _apply(flows, mod, prep, index)

    sim_prep = prep
    buffers = [m.buffer_minor for m in spec.modifiers if m.type == "buffer_override"]
    if buffers:
        if buffers[-1] is None or buffers[-1] < 0:
            raise ScenarioError("buffer_override needs a buffer of zero or more")
        sim_prep = dataclasses.replace(
            prep, inputs=dataclasses.replace(inputs, buffer_minor=buffers[-1])
        )

    base_balances = calibrate_paths(balance_paths(prep, prep.flows), calibration)
    sim_balances = calibrate_paths(balance_paths(prep, flows), calibration)
    sim_paydays = sorted({prep.dates[f.day] for f in flows if f.income_key is not None})

    baseline = summarise(prep, base_balances, forecast_hash(inputs, prior, calibration))
    simulated = summarise(
        sim_prep,
        sim_balances,
        forecast_hash(inputs, prior, calibration, extra={"scenario": spec}),
        cycle_paydays=sim_paydays,
    )
    # Compare like with like: both lows measured over the baseline's pay-cycle windows.
    sim_on_base = pay_cycle_lows(prep, sim_balances, prep.paydays)
    delta = tuple(
        (b.payday, b.low.p50, s.low.p50)
        for b, s in zip(baseline.pay_cycles, sim_on_base, strict=True)
    )
    return SimulationResult(scenario=spec, baseline=baseline, simulated=simulated, delta_lows=delta)
