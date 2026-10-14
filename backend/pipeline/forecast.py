"""Forecasts and simulations from stored data, persisted as Calculations (ENG-07, docs/07 §6).

`forecast_inputs` assembles ForecastInputs from the ledger, the detected streams and obligations,
the balance anchors and the workspace's buffer. The same stored data always yields the same inputs
(and so the same `inputs_hash` and calculation id); any ledger change bumps `data_version`, which
changes the seed and the hash.

Engine v1.3 (docs/07 §6.2b, §6.8a): every forecast carries the irregular-expense prior for its
currency (pack data, e.g. locale_packs/uk_irregular_expenses.yaml) and a calibration fitted from
the engine's own raw forecasts at weekly origins over the last three months, scored against the
balances the ledger shows since. Both are stored in the calculation's params, so `verify` rebuilds
the identical result. Caveat: those past forecasts reuse today's detected income streams and
obligations (detection is not re-run per origin), so the calibration is slightly optimistic for a
brand-new stream; the eval backtest (E-FC) re-runs detection at every origin.
"""

from __future__ import annotations

import dataclasses
import hashlib
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from backend.finance_core.calc import Calculation as CalcRecord
from backend.finance_core.calc import content_hash, recompute, record, to_jsonable
from backend.finance_core.forecast import build_forecast
from backend.finance_core.forecast.calibration import (
    MAX_LOOKBACK_DAYS,
    Calibration,
    PastForecast,
    fit_calibration,
)
from backend.finance_core.forecast.calibration import (
    from_jsonable as calibration_from_json,
)
from backend.finance_core.forecast.calibration import (
    to_jsonable as calibration_json,
)
from backend.finance_core.forecast.engine import (
    ENGINE_VERSION,
    LOOKBACK_DAYS,
    is_unscheduled_outflow,
)
from backend.finance_core.forecast.prior import IrregularPrior, load_irregular_prior
from backend.finance_core.forecast.prior import to_jsonable as prior_json
from backend.finance_core.importers.anchors import balance_on
from backend.finance_core.simulate import simulate
from backend.finance_core.types import (
    BalanceAnchor,
    FlowKind,
    ForecastInputs,
    ForecastResult,
    KnownFlow,
    ParsedRow,
    PayCycleLow,
    Quantiles,
    ScenarioModifier,
    ScenarioSpec,
    SimulationResult,
)
from backend.pipeline import ledger, packs
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext

# The engine takes up to a year of discretionary history: it bootstraps everyday spend from the
# last 90 days and estimates one-off expenses (≥3× the category median) over the whole span.
HISTORY_DAYS = LOOKBACK_DAYS
SCOPE = "all"
CALIBRATION_STEP_DAYS = 7  # past forecasts are made weekly
CALIBRATION_WARMUP_DAYS = 28  # the earliest past forecast needs four weeks of history
CALIBRATION_HORIZON_DAYS = 60
CALIBRATION_PATHS = 200  # past forecasts only need their P10/P50/P90


@lru_cache
def irregular_prior(currency: str) -> IrregularPrior | None:
    """The irregular-expense prior for a currency, from the pack data (None if there is none)."""
    for file in sorted(packs.PACK_DIR.glob("*_irregular_expenses.yaml")):
        prior = load_irregular_prior(file.read_text(encoding="utf-8"))
        if prior.currency == currency:
            return prior
    return None


class NoLedgerData(LookupError):
    pass


@dataclass(frozen=True)
class StoredForecast:
    calculation: m.Calculation
    result: ForecastResult
    inputs: ForecastInputs
    created: bool  # False when the identical question had already been answered


@dataclass(frozen=True)
class StoredSimulation:
    calculation: m.Calculation
    result: SimulationResult
    created: bool


def _seed(workspace_id: str, data_version: int, currency: str) -> int:
    key = f"{workspace_id}|{data_version}|{SCOPE}|-|{currency}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)


def _starting_balance(
    ctx: WorkspaceContext, account_ids: Sequence[str], rows: Sequence[m.Transaction], as_of: date
) -> tuple[int, str]:
    """Sum of each account's balance on `as_of`, rolled from its best anchor. Declared anchors win
    over statement balances on the same day; with no anchor at all the forecast is relative."""
    by_account: dict[str, list[ParsedRow]] = defaultdict(list)
    for r in rows:
        by_account[r.account_id].append(
            ParsedRow(
                r.source_row_index or 0, r.posted_on, r.description, r.amount_minor, r.currency
            )
        )
    total, provenances = 0, set()
    for account_id in account_ids:
        anchors = ctx.anchors(account_id)
        if not anchors:
            continue
        before = [a for a in anchors if a.as_of <= as_of]
        if before:
            best = max(before, key=lambda a: (a.as_of, a.provenance == "declared"))
        else:
            best = min(anchors, key=lambda a: (a.as_of, a.provenance != "declared"))
        anchor = BalanceAnchor(
            account_id, best.as_of, best.amount_minor, best.currency, best.source
        )
        total += balance_on(anchor, by_account[account_id], as_of)
        provenances.add("declared" if best.provenance == "declared" else "statement_column")
    if not provenances:
        return 0, "relative"
    return total, "declared" if "declared" in provenances else "statement_column"


def _discretionary(
    rows: Sequence[m.Transaction],
    latest: dict[str, m.Categorisation],
    recurring_ids: set[str],
    as_of: date,
    window_days: int,
) -> tuple[tuple[date, str, int], ...]:
    start = as_of - timedelta(days=window_days)
    return tuple(
        (r.posted_on, latest[r.id].category_key, r.amount_minor)
        for r in rows
        if start < r.posted_on <= as_of
        and r.id in latest
        and is_unscheduled_outflow(
            r.amount_minor, FlowKind(latest[r.id].flow_kind), r.id in recurring_ids
        )
    )


def forecast_inputs(
    ctx: WorkspaceContext,
    *,
    as_of: date | None = None,
    horizon_days: int = 90,
    n_paths: int = 500,
    window_days: int = HISTORY_DAYS,
    known_flows: Sequence[KnownFlow] = (),
) -> ForecastInputs:
    ws = ctx.workspace
    currency = ws.home_currency
    accounts = [
        a.id
        for a in ctx.all(m.Account)
        if a.include_in_forecast and a.tracked and a.currency == currency
    ]
    rows = ctx.transactions(account_ids=accounts, currency=currency)
    if not rows:
        raise NoLedgerData(f"no {currency} transactions in {ws.id}")
    if as_of is None:
        latest_anchor = max(
            (a.as_of for acct in accounts for a in ctx.anchors(acct)), default=rows[-1].posted_on
        )
        as_of = max(rows[-1].posted_on, latest_anchor)
    rows = [r for r in rows if r.posted_on <= as_of]
    latest = ctx.latest_categorisations()
    streams = sorted(
        (ledger.income_stream(s) for s in ctx.all(m.IncomeStream) if s.currency == currency),
        key=lambda s: s.key,
    )
    obligations = sorted(
        (ledger.obligation(o) for o in ctx.all(m.RecurringObligation) if o.currency == currency),
        key=lambda o: o.key,
    )
    recurring_ids = {i for o in obligations for i in o.member_ids}
    balance, provenance = _starting_balance(ctx, accounts, rows, as_of)
    end = as_of + timedelta(days=horizon_days)
    return ForecastInputs(
        as_of=as_of,
        currency=currency,
        starting_balance_minor=balance,
        starting_balance_provenance=provenance,
        income_streams=tuple(streams),
        obligations=tuple(obligations),
        known_flows=tuple(sorted(known_flows, key=lambda k: (k.on, k.label))),
        discretionary_history=_discretionary(rows, latest, recurring_ids, as_of, window_days),
        holidays=packs.holidays(ws.country, (rows[0].posted_on, end)),
        # A buffer-breach chance is dishonest without a real balance (docs/07 §4.1).
        buffer_minor=ws.buffer_minor if provenance != "relative" else None,
        horizon_days=horizon_days,
        n_paths=n_paths,
        seed=_seed(ws.id, ws.data_version, currency),
    )


def _daily_balances(ctx: WorkspaceContext, first: date, last: date) -> dict[date, int]:
    """End-of-day balance of the forecast's accounts for every day in [first, last], rolled from
    the best anchor and the ledger (only when the balance is real, not relative)."""
    ws = ctx.workspace
    currency = ws.home_currency
    accounts = [
        a.id
        for a in ctx.all(m.Account)
        if a.include_in_forecast and a.tracked and a.currency == currency
    ]
    rows = ctx.transactions(account_ids=accounts, currency=currency)
    start, provenance = _starting_balance(ctx, accounts, rows, first)
    if provenance == "relative":
        return {}
    net: dict[date, int] = defaultdict(int)
    for r in rows:
        if first < r.posted_on <= last:
            net[r.posted_on] += r.amount_minor
    out: dict[date, int] = {}
    balance = start
    day = first
    while day <= last:
        if day > first:
            balance += net.get(day, 0)
        out[day] = balance
        day += timedelta(days=1)
    return out


def calibration_for(
    ctx: WorkspaceContext,
    inputs: ForecastInputs,
    prior: IrregularPrior | None,
    window_days: int = HISTORY_DAYS,
) -> Calibration | None:
    """Fit the band calibration (docs/07 §6.8a) from raw forecasts at weekly origins in the last
    MAX_LOOKBACK_DAYS, scored on the ledger's balances up to `inputs.as_of`. None when the
    balance is relative or there is too little history for a single past forecast."""
    if inputs.starting_balance_provenance == "relative":
        return None
    first_day = min((d for d, _c, _a in inputs.discretionary_history), default=inputs.as_of)
    earliest = max(
        inputs.as_of - timedelta(days=MAX_LOOKBACK_DAYS),
        first_day + timedelta(days=CALIBRATION_WARMUP_DAYS),
    )
    origins = []
    origin = inputs.as_of - timedelta(days=CALIBRATION_STEP_DAYS)
    while origin >= earliest:
        origins.append(origin)
        origin -= timedelta(days=CALIBRATION_STEP_DAYS)
    if not origins:
        return None
    past = []
    for o in sorted(origins):
        past_inputs = forecast_inputs(
            ctx,
            as_of=o,
            horizon_days=CALIBRATION_HORIZON_DAYS,
            n_paths=CALIBRATION_PATHS,
            window_days=window_days,
        )
        if past_inputs.starting_balance_provenance == "relative":
            continue
        raw = build_forecast(past_inputs, prior=prior)
        past.append(PastForecast(o, raw.p10, raw.p50, raw.p90))
    if not past:
        return None
    actual = _daily_balances(ctx, past[0].origin, inputs.as_of)
    return fit_calibration(past, actual, inputs.as_of)


def _model_params(prior: IrregularPrior | None, calibration: Calibration | None) -> dict[str, Any]:
    return {
        "prior": None if prior is None else prior_json(prior),
        "calibration": None if calibration is None else calibration_json(calibration),
    }


def _params(ctx: WorkspaceContext, inputs: ForecastInputs, window_days: int) -> dict[str, Any]:
    # The workspace id keeps calculation ids distinct between workspaces with identical data.
    # Provenance is stored with the calculation so the Evidence drawer can say which figures
    # were declared by the user rather than read from a statement (docs/09 §11).
    return {
        "workspace_id": ctx.workspace_id,
        "scope": SCOPE,
        "starting_balance_provenance": inputs.starting_balance_provenance,
        "income_provenance": {
            s.key: str(getattr(s.provenance, "value", s.provenance)) for s in inputs.income_streams
        },
        "as_of": inputs.as_of.isoformat(),
        "horizon_days": inputs.horizon_days,
        "n_paths": inputs.n_paths,
        "window_days": window_days,
        "known_flows": [
            {"on": k.on.isoformat(), "amount_minor": k.amount_minor, "label": k.label,
             "category_key": k.category_key}
            for k in inputs.known_flows
        ],
    }  # fmt: skip


def _store(ctx: WorkspaceContext, rec: CalcRecord, duration_ms: int) -> tuple[m.Calculation, bool]:
    existing = ctx.calculation(rec.id)
    if existing is not None:
        return existing, False
    row = m.Calculation(
        id=rec.id,
        kind=rec.kind,
        inputs_hash=rec.inputs_hash,
        params=rec.params,
        result=rec.result,
        engine_version=rec.engine_version,
        data_version=ctx.workspace.data_version,
        duration_ms=duration_ms,
    )
    ctx.add(row)
    ctx.session.flush()
    return row, True


def _result_from_json(data: dict[str, Any]) -> ForecastResult:
    """A stored forecast result (to_jsonable shape) as the engine's ForecastResult."""
    day = date.fromisoformat

    def quantiles(q: dict[str, Any]) -> Quantiles:
        return Quantiles(int(q["p10"]), int(q["p50"]), int(q["p90"]))

    return ForecastResult(
        as_of=day(data["as_of"]),
        currency=data["currency"],
        horizon_days=int(data["horizon_days"]),
        dates=tuple(day(d) for d in data["dates"]),
        p10=tuple(int(v) for v in data["p10"]),
        p50=tuple(int(v) for v in data["p50"]),
        p90=tuple(int(v) for v in data["p90"]),
        pay_cycles=tuple(
            PayCycleLow(
                payday=day(c["payday"]),
                low=quantiles(c["low"]),
                low_date=day(c["low_date"]),
                chance_below_buffer=c["chance_below_buffer"],
            )
            for c in data["pay_cycles"]
        ),
        min_balance_p50_minor=int(data["min_balance_p50_minor"]),
        min_balance_date=day(data["min_balance_date"]),
        buffer_minor=data["buffer_minor"],
        n_paths=int(data["n_paths"]),
        seed=int(data["seed"]),
        inputs_hash=data["inputs_hash"],
        engine_version=data["engine_version"],
    )


def _stored_forecast(
    ctx: WorkspaceContext, inputs: ForecastInputs, params: dict[str, Any]
) -> m.Calculation | None:
    """The forecast already computed for these inputs and parameters, if any (docs/05 A5: read
    paths never recompute). The calibration is left out of the match: it is a function of the
    ledger at the inputs' data_version (in the seed, so in the inputs hash), the inputs, the
    prior and window_days, all of which are matched. A change to the calibration code must bump
    ENGINE_VERSION."""
    want = to_jsonable(params)
    for row in ctx.calculations("forecast", content_hash(inputs)):
        if row.engine_version == ENGINE_VERSION and all(
            row.params.get(k) == v for k, v in want.items()
        ):
            return row
    return None


def run_forecast(
    ctx: WorkspaceContext,
    *,
    as_of: date | None = None,
    horizon_days: int = 90,
    n_paths: int = 500,
    window_days: int = HISTORY_DAYS,
    known_flows: Sequence[KnownFlow] = (),
    actor: str = "system",
) -> StoredForecast:
    inputs = forecast_inputs(
        ctx,
        as_of=as_of,
        horizon_days=horizon_days,
        n_paths=n_paths,
        window_days=window_days,
        known_flows=known_flows,
    )
    prior = irregular_prior(inputs.currency)
    base = {**_params(ctx, inputs, window_days), "prior": _model_params(prior, None)["prior"]}
    stored = _stored_forecast(ctx, inputs, base)
    if stored is not None:
        return StoredForecast(stored, _result_from_json(stored.result), inputs, False)
    started = time.perf_counter()
    calibration = calibration_for(ctx, inputs, prior, window_days)
    result = build_forecast(inputs, prior=prior, calibration=calibration)
    elapsed = int((time.perf_counter() - started) * 1000)
    params = {**_params(ctx, inputs, window_days), **_model_params(prior, calibration)}
    rec = record("forecast", inputs, params, result, result.engine_version)
    row, created = _store(ctx, rec, elapsed)
    if created:
        ctx.append_audit(
            "forecast.rebuilt", "calculation", row.id, actor=actor,
            after={"as_of": inputs.as_of.isoformat(), "data_version": row.data_version},
        )  # fmt: skip
    return StoredForecast(row, result, inputs, created)


def run_simulation(
    ctx: WorkspaceContext,
    spec: ScenarioSpec,
    *,
    as_of: date | None = None,
    horizon_days: int = 90,
    n_paths: int = 500,
    window_days: int = HISTORY_DAYS,
    assumptions: Sequence[str] = (),
) -> StoredSimulation:
    """Baseline from stored data plus the scenario; the simulation reuses the baseline seed."""
    inputs = forecast_inputs(
        ctx, as_of=as_of, horizon_days=horizon_days, n_paths=n_paths, window_days=window_days
    )
    started = time.perf_counter()
    prior = irregular_prior(inputs.currency)
    calibration = calibration_for(ctx, inputs, prior, window_days)
    result = simulate(inputs, spec, prior=prior, calibration=calibration)
    elapsed = int((time.perf_counter() - started) * 1000)
    params = {
        **_params(ctx, inputs, window_days),
        **_model_params(prior, calibration),
        "spec": spec,
    }
    if assumptions:  # e.g. an owner-decided default date, stated with the evidence
        params["assumptions"] = list(assumptions)
    rec = record("simulation", inputs, params, result, result.simulated.engine_version)
    row, created = _store(ctx, rec, elapsed)
    return StoredSimulation(row, result, created)


_MODIFIER_DATES = ("date", "from_date", "to_date")


def _spec_json(spec: ScenarioSpec) -> dict[str, Any]:
    """A ScenarioSpec as JSON, every modifier field kept, so it can be rebuilt exactly."""
    mods = []
    for mod in spec.modifiers:
        out: dict[str, Any] = {}
        for key, value in dataclasses.asdict(mod).items():
            if value in (None, ""):
                continue
            out[key] = value.isoformat() if key in _MODIFIER_DATES else value
        mods.append(out)
    return {
        "name": spec.name,
        "currency": spec.currency,
        "modifiers": mods,
        "horizon_days": spec.horizon_days,
    }


def spec_from_json(raw: dict[str, Any]) -> ScenarioSpec:
    """A stored ScenarioSpec (from `_spec_json` or the engine's own JSON) back as the dataclass."""
    mods: list[ScenarioModifier] = []
    for mod in raw.get("modifiers") or []:
        fields: dict[str, Any] = {
            k: date.fromisoformat(v) if k in _MODIFIER_DATES and isinstance(v, str) else v
            for k, v in mod.items()
        }
        mods.append(ScenarioModifier(**fields))
    return ScenarioSpec(
        name=str(raw["name"]),
        currency=str(raw["currency"]),
        modifiers=tuple(mods),
        horizon_days=raw.get("horizon_days"),
    )


def store_impact_simulation(
    ctx: WorkspaceContext, inputs: ForecastInputs, spec: ScenarioSpec, *, window_days: int
) -> StoredSimulation:
    """Persist the simulation behind a recommendation's checked impact (docs/06 §10.2:
    `rec_ → impact calc_ → sim_`). It is exactly the computation the Verifier recomputed the
    impact with (`agents.advice.impact.recompute_impact`: the same inputs, `simulate` with no
    prior or calibration), so the stored figures are the ones the card shows and `verify_simulation`
    can rebuild them."""
    started = time.perf_counter()
    result = simulate(inputs, spec)
    elapsed = int((time.perf_counter() - started) * 1000)
    params = {
        **_params(ctx, inputs, window_days),
        **_model_params(None, None),
        "spec": _spec_json(spec),
        "purpose": "recommendation_impact",
    }
    rec = record("simulation", inputs, params, result, result.simulated.engine_version)
    row, created = _store(ctx, rec, elapsed)
    return StoredSimulation(row, result, created)


def _inputs_from_params(ctx: WorkspaceContext, p: dict[str, Any]) -> ForecastInputs:
    return forecast_inputs(
        ctx,
        as_of=date.fromisoformat(p["as_of"]),
        horizon_days=p["horizon_days"],
        n_paths=p["n_paths"],
        window_days=p["window_days"],
        known_flows=[
            KnownFlow(date.fromisoformat(k["on"]), k["amount_minor"], k["label"], k["category_key"])
            for k in p["known_flows"]
        ],
    )


def verify_simulation(ctx: WorkspaceContext, calc_id: str) -> bool:
    """Rebuild a stored simulation from the stored data and its stored spec, prior and
    calibration; True when the inputs hash and the result are identical (raises ValueError when
    the stored data has changed since, like `verify`)."""
    row = ctx.calculation(calc_id)
    if row is None or row.kind != "simulation":
        raise LookupError(calc_id)
    p = row.params
    inputs = _inputs_from_params(ctx, p)
    spec = spec_from_json(p["spec"])
    prior = irregular_prior(inputs.currency) if p.get("prior") is not None else None
    calibration = (
        calibration_from_json(p["calibration"]) if p.get("calibration") is not None else None
    )
    stored = CalcRecord(
        row.id, row.kind, row.inputs_hash, row.params, row.result, row.engine_version
    )
    _, same = recompute(
        stored, inputs, lambda i: simulate(i, spec, prior=prior, calibration=calibration)
    )
    return same


def verify(ctx: WorkspaceContext, calc_id: str) -> bool:
    """Rebuild a stored forecast from today's stored data and check that both the inputs hash and
    the result are identical. Raises ValueError when the stored data has changed since (stale)."""
    row = ctx.calculation(calc_id)
    if row is None or row.kind != "forecast":
        raise LookupError(calc_id)
    p = row.params
    inputs = _inputs_from_params(ctx, p)
    stored = CalcRecord(
        row.id, row.kind, row.inputs_hash, row.params, row.result, row.engine_version
    )
    # Rebuild with the calibration the forecast was made with (stored in its params) and the
    # current prior; if the prior's pack data has changed since, the result differs (not same).
    prior = irregular_prior(inputs.currency) if p.get("prior") is not None else None
    calibration = (
        calibration_from_json(p["calibration"]) if p.get("calibration") is not None else None
    )
    _, same = recompute(
        stored, inputs, lambda i: build_forecast(i, prior=prior, calibration=calibration)
    )
    return same
