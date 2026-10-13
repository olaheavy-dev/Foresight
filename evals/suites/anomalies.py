"""E-ANOM, trend part only (docs/09 §6.6): category spikes on *-base vs *-clean twins.

Subscription overlap and price-rise findings are scored in E-REC. Detection latency, the
sensitivity sweep and the other finding types arrive with the Analyst in Stage 3.
"""

from __future__ import annotations

from typing import Any

from backend.finance_core.detect.trends import category_trends
from evals.common import build_ledger, load_dataset
from evals.metrics import r4
from evals.suites import Target, target

SUITE_ID = "E-ANOM"
NAME = "anomalies"
BASE = ["P1-base", "P2-base"]
CLEAN = ["P1-clean", "P2-clean"]


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
    clean_fp = 0
    for name in clean:
        spikes, _truth = _findings(name)
        clean_fp += len(spikes)
        per[name] = {"spikes": spikes}
    fp_rate = clean_fp / len(clean) if clean else None
    metrics: dict[str, Any] = {
        "scope": "category_trend findings only",
        "recall": r4(n_recalled / n_truth) if n_truth else None,
        "precision": r4(n_true_spikes / n_spikes) if n_spikes else None,
        "fp_per_persona_month_clean": r4(fp_rate),
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
            ", ".join(clean),
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
        "Trend part only: one 30-day window at as_of per persona, so one persona-month each.",
        "A spike matches an injected anomaly when its category equals the anomaly subject.",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
