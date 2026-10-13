"""Forecasts and simulations from stored data, persisted as Calculations (ENG-07, docs/07 §6).

`forecast_inputs` assembles ForecastInputs from the ledger, the detected streams and obligations,
the balance anchors and the workspace's buffer. The same stored data always yields the same inputs
(and so the same `inputs_hash` and calculation id); any ledger change bumps `data_version`, which
changes the seed and the hash.
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.finance_core.calc import Calculation as CalcRecord
from backend.finance_core.calc import recompute, record
from backend.finance_core.forecast import build_forecast
from backend.finance_core.forecast.engine import LOOKBACK_DAYS, is_unscheduled_outflow
from backend.finance_core.importers.anchors import balance_on
from backend.finance_core.simulate import simulate
from backend.finance_core.types import (
    BalanceAnchor,
    FlowKind,
    ForecastInputs,
    ForecastResult,
    KnownFlow,
    ParsedRow,
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


def _params(ctx: WorkspaceContext, inputs: ForecastInputs, window_days: int) -> dict[str, Any]:
    # The workspace id keeps calculation ids distinct between workspaces with identical data.
    return {
        "workspace_id": ctx.workspace_id,
        "scope": SCOPE,
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
    started = time.perf_counter()
    result = build_forecast(inputs)
    elapsed = int((time.perf_counter() - started) * 1000)
    rec = record(
        "forecast", inputs, _params(ctx, inputs, window_days), result, result.engine_version
    )
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
) -> StoredSimulation:
    """Baseline from stored data plus the scenario; the simulation reuses the baseline seed."""
    inputs = forecast_inputs(
        ctx, as_of=as_of, horizon_days=horizon_days, n_paths=n_paths, window_days=window_days
    )
    started = time.perf_counter()
    result = simulate(inputs, spec)
    elapsed = int((time.perf_counter() - started) * 1000)
    params = {**_params(ctx, inputs, window_days), "spec": spec}
    rec = record("simulation", inputs, params, result, result.simulated.engine_version)
    row, created = _store(ctx, rec, elapsed)
    return StoredSimulation(row, result, created)


def verify(ctx: WorkspaceContext, calc_id: str) -> bool:
    """Rebuild a stored forecast from today's stored data and check that both the inputs hash and
    the result are identical. Raises ValueError when the stored data has changed since (stale)."""
    row = ctx.calculation(calc_id)
    if row is None or row.kind != "forecast":
        raise LookupError(calc_id)
    p = row.params
    inputs = forecast_inputs(
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
    stored = CalcRecord(
        row.id, row.kind, row.inputs_hash, row.params, row.result, row.engine_version
    )
    _, same = recompute(stored, inputs, build_forecast)
    return same
