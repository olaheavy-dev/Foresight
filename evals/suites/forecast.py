"""E-FC: rolling-origin backtest (docs/09 §7) through `finance_core.forecast.backtest`.

Inputs at each origin come from the full deterministic pipeline run on the history truncated to
the origin (import → rules categorisation → income and recurring detection → discretionary
history), so nothing after the origin leaks in. The anchor is the truth balance at the origin
(§7.1 step 2). Baselines B0–B3 are the ones `backtest` computes.

Engine v1.3 (docs/07 §6.2b, §6.8a): every forecast carries the ONS irregular-expense prior, and
each scored forecast is calibrated from the engine's raw forecasts at earlier weekly origins
(from day CALIBRATION_WARMUP_DAYS), scored only on balances up to the origin, as the product does.

Results are also split into dev and test origins (docs/09 §3.8): an origin is dev when its
60-day window ends at least three months before the data's last day. Engine choices (prior
strength, event interval, calibration buckets) were made on dev origins only.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Sequence
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.finance_core.detect.income import detect_income_streams
from backend.finance_core.detect.recurring import detect_recurring
from backend.finance_core.forecast.backtest import BASELINES, backtest, summarise_origins
from backend.finance_core.forecast.calibration import CALIBRATION_VERSION
from backend.finance_core.forecast.engine import (
    ENGINE_VERSION,
    LOOKBACK_DAYS,
    is_unscheduled_outflow,
)
from backend.finance_core.forecast.prior import IrregularPrior, load_irregular_prior
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
CALIBRATION_WARMUP_DAYS = 28  # earliest calibration-only origin (4 weeks of history)
DEV_GAP_MONTHS = 3  # dev origins' windows end at least this many months before the data ends
PRIOR_PATH = (
    Path(__file__).resolve().parents[2]
    / "backend"
    / "finance_core"
    / "locale_packs"
    / "uk_irregular_expenses.yaml"
)
# Arms. The headline arm simulates the user answering the onboarding question about detected
# income (docs/06 H8, docs/00 §6a) from the truth labels; the other arm takes detection as is.
ARM_CONFIRMED = "with_onboarding_confirmation"
ARM_UNCONFIRMED = "no_confirmation"
HEADLINE_ARM = ARM_CONFIRMED
ARM_NOTES = {
    ARM_CONFIRMED: "simulates the user confirming detected income at onboarding (06 H8): the top "
    f"{QUESTIONS} unconfirmed payers at each origin are asked about and answered from the truth "
    "labels",
    ARM_UNCONFIRMED: "detection only: no user answers",
}


@lru_cache
def uk_irregular_prior() -> IrregularPrior:
    return load_irregular_prior(PRIOR_PATH.read_text(encoding="utf-8"))


def _months_before(d: date, months: int) -> date:
    month = d.month - 1 - months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, _calendar.monthrange(year, month)[1]))


def is_dev(origin: date, last_day: date, max_h: int = max(HORIZONS)) -> bool:
    """docs/09 §3.8: the origin's window ends at least DEV_GAP_MONTHS before the data ends."""
    return origin + timedelta(days=max_h) <= _months_before(last_day, DEV_GAP_MONTHS)


def calibration_origins_for(history: dict[date, int], first_scored: date | None) -> list[date]:
    """Weekly calibration-only origins from day CALIBRATION_WARMUP_DAYS up to the first scored
    origin (scored origins also serve as calibration windows for later ones)."""
    days = sorted(history)
    if not days or first_scored is None:
        return []
    out = []
    d = days[0] + timedelta(days=CALIBRATION_WARMUP_DAYS)
    while d < first_scored:
        if d in history:
            out.append(d)
        d += timedelta(days=STEP_DAYS)
    return out


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


def inputs_at(
    ds: Dataset, ledger: Ledger, account: str, origin: date, confirm: bool = True
) -> ForecastInputs:
    """ForecastInputs as they would have been known at `origin` (truncated ledger). With
    `confirm`, the onboarding income question is answered as the user would (ARM_CONFIRMED)."""
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
        confirmed_sources=confirmed_income_sources(txns, cats, ledger) if confirm else (),
    )
    report = detect_recurring(txns, cats, pack, hol)
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


def _dataset(
    name: str, confirm: bool = True, *, use_prior: bool = True, calibrate: bool = True
) -> dict[str, Any]:
    ds = load_dataset(name)
    account = str(ds.accounts[0]["id"])
    ledger = build_ledger(ds)
    history = ds.balances(account)
    origins = origins_for(history)
    cal_origins = calibration_origins_for(history, origins[0] if origins else None)
    leaks = 0

    def build(origin: date) -> ForecastInputs:
        nonlocal leaks
        inputs = inputs_at(ds, ledger, account, origin, confirm)
        leaks += sum(1 for d, _c, _a in inputs.discretionary_history if d > origin)
        return inputs

    result = backtest(
        history,
        origins,
        build,
        HORIZONS,
        prior=uk_irregular_prior() if use_prior else None,
        calibrate=calibrate,
        calibration_origins=cal_origins,
    )
    last_day = max(history)
    per_origin = result.pop("per_origin")
    splits = {
        split: summarise_origins(
            [r for r in per_origin if is_dev(date.fromisoformat(r["origin"]), last_day) == dev],
            HORIZONS,
        )
        for split, dev in (("dev", True), ("test", False))
    }
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
    best_mase: dict[str, Any] = {}
    for h in HORIZONS:
        mases = {b: result["baselines"][b]["mase"][str(h)] for b in BASELINES}
        scored_m = {k: v for k, v in mases.items() if v is not None}
        if scored_m:
            name_m = min(scored_m, key=lambda k: scored_m[k])
            best_mase[str(h)] = {"baseline": name_m, "mase": scored_m[name_m]}
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
        "best_baseline_mase": best_mase,
        "splits": splits,
        "calibration_origins": len(cal_origins),
        "skill_vs_B2": skill_b2,
        "skill_vs_best_baseline": skill_best,
        "leaked_rows": leaks,
    }


def _gbp(minor: float | None) -> float | None:
    return None if minor is None else round(minor / 100, 2)


def _split_view(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "n_origins": summary["n_origins"],
        "coverage_p10_p90": summary["coverage_p10_p90"],
        "mae30_gbp": _gbp(summary["mae_minor"]["30"]),
        "mase30": summary["mase"]["30"],
        "pinball_gbp": _gbp(summary["pinball_minor"]),
        "mape30": summary["mape"]["30"],
    }


def _arm_summary(per: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "coverage_by_dataset": {n: d["foresight"]["coverage_p10_p90"] for n, d in per.items()},
        "mae30_gbp_by_dataset": {
            n: _gbp(d["foresight"]["mae_minor"]["30"]) for n, d in per.items()
        },
        "mase30_by_dataset": {n: d["foresight"]["mase"]["30"] for n, d in per.items()},
        "pinball_gbp_by_dataset": {
            n: _gbp(d["foresight"].get("pinball_minor")) for n, d in per.items()
        },
    }


def run(fast: bool = False) -> dict[str, Any]:
    names = ["P1-base"] if fast else DATASETS
    per = {n: _dataset(n, confirm=True) for n in names}
    arms = {ARM_CONFIRMED: {"note": ARM_NOTES[ARM_CONFIRMED], **_arm_summary(per)}}
    if not fast:
        unconfirmed = {n: _dataset(n, confirm=False) for n in names}
        arms[ARM_UNCONFIRMED] = {"note": ARM_NOTES[ARM_UNCONFIRMED], **_arm_summary(unconfirmed)}
    p1 = per["P1-base"]
    gbp = _gbp

    by_horizon = {
        str(h): {
            "mae_gbp": gbp(p1["foresight"]["mae_minor"][str(h)]),
            "mase": p1["foresight"]["mase"][str(h)],
            "best_baseline_mase": p1["best_baseline_mase"].get(str(h), {}).get("mase"),
            "mape": p1["foresight"]["mape"][str(h)],
            "coverage_p10_p90": p1["foresight"]["coverage_p10_p90"],
            "best_baseline": p1["best_baseline"].get(str(h), {}).get("baseline"),
            "best_baseline_mae_gbp": gbp(p1["best_baseline"].get(str(h), {}).get("mae_minor")),
        }
        for h in HORIZONS
    }
    coverages = {n: d["foresight"]["coverage_p10_p90"] for n, d in per.items()}
    mase30 = p1["foresight"]["mase"]["30"]
    best_mase30 = p1["best_baseline_mase"].get("30", {}).get("mase")
    metrics: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "prior": uk_irregular_prior().source,
        "headline_dataset": "P1-base",
        "headline_arm": HEADLINE_ARM,
        "simulated_user_step": ARM_NOTES[HEADLINE_ARM],
        "arms": arms,
        "pinball_gbp_by_dataset": arms[HEADLINE_ARM]["pinball_gbp_by_dataset"],
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
        "mase30_by_dataset": {n: d["foresight"]["mase"]["30"] for n, d in per.items()},
        "best_baseline_mase30_by_dataset": {
            n: d["best_baseline_mase"].get("30", {}).get("mase") for n, d in per.items()
        },
        "by_split": {
            n: {split: _split_view(v) for split, v in d["splits"].items()} for n, d in per.items()
        },
        "pay_cycle_low_mae_gbp": gbp(p1["foresight"]["pay_cycle_low_mae_minor"]),
        "breach_brier": None,
        "by_dataset": per,
        "method": {
            "origins": f"every {STEP_DAYS} days from day {WARMUP_DAYS} to end − {max(HORIZONS)}",
            "n_paths": N_PATHS,
            "inputs": "detected (import → rules → detect), truncated at each origin",
            "anchor": "truth balance at the origin",
            "mape": "reported, not a target: |error| / |actual| explodes near £0, exactly the "
            "pre-payday lows that matter (target replaced by MASE on 13 Oct 2026)",
            "mase": "MAE ÷ the in-sample mean absolute h-step change before each origin "
            "(Hyndman & Koehler 2006); below 1 beats in-sample naive",
            "calibration": f"{CALIBRATION_VERSION}: tail scales from raw forecasts at earlier "
            f"weekly origins (from day {CALIBRATION_WARMUP_DAYS}), scored up to the origin",
            "dev_test": f"dev = origin + {max(HORIZONS)} d ≤ last day − {DEV_GAP_MONTHS} months",
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
        target("FC-mase", "MASE(30)", mase30, "<", 1.0, "P1"),
        target(
            "FC-mase-vs-best",
            "MASE(30) ÷ best naive baseline MASE(30)",
            round(mase30 / best_mase30, 4) if mase30 is not None and best_mase30 else None,
            "<",
            1.0,
            "P1",
        ),
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
        "Headline numbers simulate the user confirming detected income at onboarding (06 H8): "
        f"the top {QUESTIONS} unconfirmed payers at each origin are answered from the truth "
        "labels. The no-confirmation arm (detection only) is reported alongside in "
        "forecast.arms.",
        "S4-shock coverage after the shift is expected to miss (docs/09 §7.4) and is not gated.",
        "Every forecast carries the ONS FYE 2025 irregular-expense prior (docs/07 §6.2b) and is "
        "calibrated from the engine's own earlier forecasts, scored only up to the origin "
        "(docs/07 §6.8a). Dev/test splits are in forecast.by_split.",
        "MAPE is reported but no longer a target (owner decision 13 Oct 2026): it divides by a "
        "balance that is near £0 at the pre-payday lows. FC-mase replaces FC-mape.",
        "Breach Brier and the long-January check are not computed yet.",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
