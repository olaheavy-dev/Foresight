"""E-FC: rolling-origin backtest (docs/09 §7) through `finance_core.forecast.backtest`.

Inputs at each origin come from the full deterministic pipeline run on the history truncated to
the origin (import → rules categorisation → income and recurring detection → discretionary
history), so nothing after the origin leaks in. The anchor is the truth balance at the origin
(§7.1 step 2). Baselines B0–B3 are the ones `backtest` computes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from backend.finance_core.detect.income import detect_income_streams
from backend.finance_core.detect.recurring import detect_recurring
from backend.finance_core.forecast.backtest import BASELINES, backtest
from backend.finance_core.forecast.engine import (
    ENGINE_VERSION,
    LOOKBACK_DAYS,
    is_unscheduled_outflow,
)
from backend.finance_core.types import Categorisation, FlowKind, ForecastInputs, Transaction
from evals.common import (
    Dataset,
    Ledger,
    build_ledger,
    load_dataset,
    majority,
    stable_seed,
    uk_categorisation_pack,
    uk_holidays,
)
from evals.metrics import r4
from evals.suites import Target, target

SUITE_ID = "E-FC"
NAME = "forecast"
DATASETS = ["P1-base", "P2-base", "S4-shock"]
HORIZONS = (7, 30, 60)
WARMUP_DAYS = 90
STEP_DAYS = 7
N_PATHS = 500
QUESTIONS = 3  # "Check what we found" asks about at most three unconfirmed payers


def confirmed_income_sources(
    txns: Sequence[Transaction], cats: Sequence[Categorisation], ledger: Ledger
) -> frozenset[str]:
    """Simulate the user's answers in "Check what we found" (docs/00 §6a): at most the top
    QUESTIONS unconfirmed payers by total, as known at the origin, are asked about, and the user
    answers "Salary/income" when the truth labels their credits as income."""
    totals: dict[str, int] = {}
    rows: dict[str, list[str]] = {}
    for t, c in zip(txns, cats, strict=True):
        if t.amount_minor > 0 and c.flow_kind is FlowKind.INFLOW_UNCONFIRMED:
            source = t.counterparty or t.normalised
            totals[source] = totals.get(source, 0) + t.amount_minor
            rows.setdefault(source, []).append(t.id)
    asked = sorted(totals, key=lambda s: (-totals[s], s))[:QUESTIONS]
    return frozenset(
        s
        for s in asked
        if majority(str(ledger.truth.get(i, {}).get("flow") or "") for i in rows[s]) == "income"
    )


def inputs_at(ds: Dataset, ledger: Ledger, account: str, origin: date) -> ForecastInputs:
    """ForecastInputs as they would have been known at `origin` (truncated ledger)."""
    pack = uk_categorisation_pack()
    keep = [i for i, t in enumerate(ledger.txns) if t.posted_on <= origin]
    txns = [ledger.txns[i] for i in keep]
    cats = [ledger.cats[i] for i in keep]
    hol = uk_holidays(origin.year - 2, origin.year + 1)
    streams = detect_income_streams(
        txns,
        cats,
        hol,
        pack.payday_shift,
        pack.one_off_multiple,
        confirmed_sources=confirmed_income_sources(txns, cats, ledger),
    )
    report = detect_recurring(txns, cats, pack)
    recurring_ids = {m for ob in report.obligations for m in ob.member_ids}
    window_start = origin - timedelta(days=LOOKBACK_DAYS - 1)
    history = tuple(
        (t.posted_on, c.category_key, t.amount_minor)
        for t, c in zip(txns, cats, strict=True)
        if window_start <= t.posted_on <= origin
        and is_unscheduled_outflow(t.amount_minor, c.flow_kind, t.id in recurring_ids)
    )
    balance = ds.balances(account)[origin]
    return ForecastInputs(
        as_of=origin,
        currency=ledger.currency,
        starting_balance_minor=balance,
        starting_balance_provenance="statement_column",
        income_streams=streams,
        obligations=report.obligations,
        known_flows=(),
        discretionary_history=history,
        holidays=hol,
        buffer_minor=ds.workspace.get("buffer_minor"),
        horizon_days=max(HORIZONS),
        n_paths=N_PATHS,
        seed=stable_seed(ds.name, origin.isoformat(), account),
    )


def origins_for(history: dict[date, int], max_h: int = max(HORIZONS)) -> list[date]:
    days = sorted(history)
    if not days:
        return []
    first, last = days[0] + timedelta(days=WARMUP_DAYS), days[-1] - timedelta(days=max_h)
    out = []
    d = first
    while d <= last:
        if d in history:
            out.append(d)
        d += timedelta(days=STEP_DAYS)
    return out


def _dataset(name: str) -> dict[str, Any]:
    ds = load_dataset(name)
    account = str(ds.accounts[0]["id"])
    ledger = build_ledger(ds)
    history = ds.balances(account)
    origins = origins_for(history)
    leaks = 0

    def build(origin: date) -> ForecastInputs:
        nonlocal leaks
        inputs = inputs_at(ds, ledger, account, origin)
        leaks += sum(1 for d, _c, _a in inputs.discretionary_history if d > origin)
        return inputs

    result = backtest(history, origins, build, HORIZONS)
    ours = result["foresight"]["mae_minor"]
    best: dict[str, Any] = {}
    for h in HORIZONS:
        scores = {b: result["baselines"][b]["mae_minor"][str(h)] for b in BASELINES}
        scored = {k: v for k, v in scores.items() if v is not None}
        if scored:
            name_b = min(scored, key=lambda k: scored[k])
            best[str(h)] = {"baseline": name_b, "mae_minor": scored[name_b]}
    skill_b2: dict[str, float | None] = {}
    for h in HORIZONS:
        b2 = result["baselines"]["B2"]["mae_minor"][str(h)]
        o = ours[str(h)]
        skill_b2[str(h)] = r4(1 - o / b2) if o is not None and b2 else None
    skill_best = {
        str(h): r4(1 - ours[str(h)] / best[str(h)]["mae_minor"])
        if ours[str(h)] is not None and str(h) in best and best[str(h)]["mae_minor"]
        else None
        for h in HORIZONS
    }
    return {
        **result,
        "account": account,
        "currency": ledger.currency,
        "first_origin": origins[0].isoformat() if origins else None,
        "last_origin": origins[-1].isoformat() if origins else None,
        "best_baseline": best,
        "skill_vs_B2": skill_b2,
        "skill_vs_best_baseline": skill_best,
        "leaked_rows": leaks,
    }


def run(fast: bool = False) -> dict[str, Any]:
    names = ["P1-base"] if fast else DATASETS
    per = {n: _dataset(n) for n in names}
    p1 = per["P1-base"]

    def gbp(minor: float | None) -> float | None:
        return None if minor is None else round(minor / 100, 2)

    by_horizon = {
        str(h): {
            "mae_gbp": gbp(p1["foresight"]["mae_minor"][str(h)]),
            "mape": p1["foresight"]["mape"][str(h)],
            "coverage_p10_p90": p1["foresight"]["coverage_p10_p90"],
            "best_baseline": p1["best_baseline"].get(str(h), {}).get("baseline"),
            "best_baseline_mae_gbp": gbp(p1["best_baseline"].get(str(h), {}).get("mae_minor")),
        }
        for h in HORIZONS
    }
    coverages = {n: d["foresight"]["coverage_p10_p90"] for n, d in per.items()}
    metrics: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "headline_dataset": "P1-base",
        "by_horizon": by_horizon,
        "skill_vs": {
            "B1-repeat30": p1["skill_vs_B1"],
            "B2-meanflow": p1["skill_vs_B2"],
            "best_baseline": p1["skill_vs_best_baseline"],
        },
        "coverage_by_dataset": coverages,
        "mae30_gbp_by_dataset": {n: gbp(d["foresight"]["mae_minor"]["30"]) for n, d in per.items()},
        "best_baseline_mae30_gbp_by_dataset": {
            n: gbp(d["best_baseline"].get("30", {}).get("mae_minor")) for n, d in per.items()
        },
        "pay_cycle_low_mae_gbp": gbp(p1["foresight"]["pay_cycle_low_mae_minor"]),
        "breach_brier": None,
        "by_dataset": per,
        "method": {
            "origins": f"every {STEP_DAYS} days from day {WARMUP_DAYS} to end − {max(HORIZONS)}",
            "n_paths": N_PATHS,
            "inputs": "detected (import → rules → detect), truncated at each origin",
            "anchor": "truth balance at the origin",
            "mape": "as computed by finance_core backtest: |error| / |actual| (no £250 floor)",
        },
    }
    targets: list[Target] = [
        target(
            "FC-skill-B1",
            "Skill vs B1-repeat30, MAE(30)",
            p1["skill_vs_B1"]["30"],
            ">=",
            0.20,
            "P1",
        ),
        target(
            "FC-skill-B2",
            "Skill vs B2-meanflow, MAE(30)",
            p1["skill_vs_B2"]["30"],
            ">=",
            0.15,
            "P1",
        ),
        target("FC-mape", "MAPE(30)", p1["foresight"]["mape"]["30"], "<=", 0.12, "P1"),
    ]
    for n in ("P1-base", "P2-base"):
        if n in per:
            targets.append(
                target(
                    f"FC-coverage-{n.split('-')[0]}",
                    "P10–P90 coverage (all h)",
                    coverages[n],
                    "range",
                    (0.72, 0.88),
                    n,
                )
            )
    if any(d["leaked_rows"] for d in per.values()):
        targets.append(target("FC-leakage", "Rows after the origin in inputs", 1.0, "==", 0, "all"))
    notes = [
        "Inputs are built from detected data with finance_core only; truth is used for the "
        "anchor balance at each origin and for scoring.",
        "Discretionary history passed to the engine covers up to 365 days before each origin "
        "and every unscheduled outflow (not only spending); the engine bootstraps everyday "
        "outflows from the last 90 days and models one-offs over the span.",
        "Check what we found is simulated: the top 3 unconfirmed payers at each origin are asked "
        "about and answered from the truth labels, as a user would (docs/00 §6a).",
        "S4-shock coverage after the shift is expected to miss (docs/09 §7.4) and is not gated.",
        "Breach Brier and the long-January check are not computed yet.",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
