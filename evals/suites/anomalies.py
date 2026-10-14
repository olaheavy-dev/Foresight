"""E-ANOM, trend part only (docs/09 §6.6): category spikes on *-base vs *-clean twins.

Subscription overlap and price-rise findings are scored in E-REC. Detection latency, the
sensitivity sweep and the other finding types arrive with the Analyst in Stage 3.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.finance_core.detect.trends import MAX_PRIOR_WINDOWS, WINDOW_DAYS, category_trends
from evals.common import build_ledger, load_dataset
from evals.metrics import r4
from evals.suites import Target, target

SUITE_ID = "E-ANOM"
NAME = "anomalies"
BASE = ["P1-base", "P2-base"]
CLEAN = ["P1-clean", "P2-clean"]


def _origins(first: date, as_of: date) -> list[date]:
    """Monthly origins (as_of, as_of − 30 d, …) that have a full baseline behind them."""
    need = timedelta(days=(MAX_PRIOR_WINDOWS + 1) * WINDOW_DAYS - 1)
    out, origin = [], as_of
    while origin - need >= first:
        out.append(origin)
        origin -= timedelta(days=WINDOW_DAYS)
    return out or [as_of]


def _clean_months(name: str) -> list[dict[str, Any]]:
    """Every scored persona-month of a clean twin: its origin and the spikes found there."""
    ds = load_dataset(name)
    ledger = build_ledger(ds)
    first = min(t.posted_on for t in ledger.txns)
    months = []
    for origin in _origins(first, ds.as_of):
        txns = [t for t in ledger.txns if t.posted_on <= origin]
        found = [t.category_key for t in category_trends(txns, ledger.cats, origin) if t.is_spike]
        months.append({"as_of": origin.isoformat(), "spikes": found})
    return months


def _findings(name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ds = load_dataset(name)
    ledger = build_ledger(ds)
    trends = category_trends(ledger.txns, ledger.cats, ds.as_of)
    spikes = [
        {
            "subject": t.category_key,
            "change_pct": round(t.change_share * 100, 1),
            "robust_z": None if t.robust_z == float("inf") else round(t.robust_z, 2),
            "recent_minor": t.recent_minor,
            "usual_minor": t.usual_minor,
            "count": t.count,
        }
        for t in trends
        if t.is_spike
    ]
    truth = [
        a
        for a in ds.truth_json("truth_anomalies.json")["anomalies"]
        if a.get("type") == "category_trend"
    ]
    return spikes, truth


def run(fast: bool = False) -> dict[str, Any]:
    base = ["P1-base"] if fast else BASE
    clean = ["P1-clean"] if fast else CLEAN
    n_truth = n_recalled = n_spikes = n_true_spikes = 0
    magnitude_errors: list[float] = []
    per: dict[str, Any] = {}
    for name in base:
        spikes, truth = _findings(name)
        subjects = {s["subject"]: s for s in spikes}
        n_spikes += len(spikes)
        wanted = {str(a["subject"]) for a in truth}
        n_true_spikes += sum(1 for s in spikes if s["subject"] in wanted)
        for a in truth:
            n_truth += 1
            hit = subjects.get(str(a["subject"]))
            if hit:
                n_recalled += 1
                if a.get("magnitude_pct") is not None:
                    magnitude_errors.append(abs(hit["change_pct"] - float(a["magnitude_pct"])))
        per[name] = {"spikes": spikes, "truth": truth}
    clean_fp = clean_months = 0
    for name in clean:
        months = _clean_months(name)
        clean_fp += sum(len(m["spikes"]) for m in months)
        clean_months += len(months)
        per[name] = {"months": months}
    fp_rate = clean_fp / clean_months if clean_months else None
    metrics: dict[str, Any] = {
        "scope": "category_trend findings only",
        "recall": r4(n_recalled / n_truth) if n_truth else None,
        "precision": r4(n_true_spikes / n_spikes) if n_spikes else None,
        "fp_per_persona_month_clean": r4(fp_rate),
        "clean_persona_months": clean_months,
        "magnitude_error_pp": r4(max(magnitude_errors)) if magnitude_errors else None,
        "by_dataset": per,
    }
    targets: list[Target] = [
        target(
            "ANOM-recall",
            "Recall (category trends)",
            metrics["recall"],
            ">=",
            0.85,
            ", ".join(base),
        ),
        target(
            "ANOM-precision",
            "Precision (category trends)",
            metrics["precision"],
            ">=",
            0.75,
            ", ".join(base),
        ),
        target(
            "ANOM-fp",
            "False positives per persona-month (clean)",
            metrics["fp_per_persona_month_clean"],
            "<=",
            0.5,
            f"{', '.join(clean)} ({clean_months} months)",
        ),
        target(
            "ANOM-magnitude",
            "Surge magnitude error (pp)",
            metrics["magnitude_error_pp"],
            "<=",
            5,
            ", ".join(base),
        ),
    ]
    notes = [
        "Trend part only. Recall and precision: one 30-day window at as_of per base persona, where "
        "the anomalies are injected. False positives: every monthly origin of the clean twins with "
        f"a full {MAX_PRIOR_WINDOWS}-window baseline behind it.",
        "A spike matches an injected anomaly when its category equals the anomaly subject.",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
