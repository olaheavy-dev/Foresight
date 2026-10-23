"""E-EFF: cost and latency of whole answers (docs/09 §10f), the two core metrics next to accuracy.

Measured on the E-UI test questions answered through the real graph (the same answers E-UI
scores, computed once per process): per answer type (simple vs advice) and per model tier.

- **cost** per answer: provider `usage` × the price table, summed over the run's steps;
- **end-to-end latency** per answer: local time measured in replay plus each step's model wait,
  built from the live latencies stored in the cassettes (`evals/efficiency.py`);
- **time to first step**: until the first progress step is written (what the SSE stream shows).

Only replay measures latency: a record run mixes live and replayed calls. An answer with a call
recorded before latency was kept is "not measured" and counted, never estimated.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from evals.assistant import eval_mode, eval_model_client
from evals.common import read_jsonl
from evals.efficiency import estimate_e2e
from evals.suites import Target, target, ui

SUITE_ID = "E-EFF"
NAME = "efficiency"
# docs/09 §10f: the accuracy gates each tier's model must pass (model selection rule, docs/00 §8).
TIER_GATES = {
    "fast": ("E-CTX", "E-UI", "E-SCN", "E-CAT"),
    "reasoning": ("E-ORC", "E-GRD"),
    "verifier": ("E-VER",),
}


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in 0–100); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _s(ms: float | None) -> float | None:
    return None if ms is None else round(ms / 1000, 2)


def _usd(x: float | None) -> float | None:
    return None if x is None else round(x, 5)


def _group(every: list[dict[str, Any]], tier_p50_ms: dict[str, float]) -> dict[str, Any]:
    answers = [a for a in every if not a["degraded"]]
    costs = [a["cost_usd"] for a in answers if a["cost_usd"] is not None]
    e2e = [a["e2e_ms"] for a in answers if a["e2e_ms"] is not None]
    first = [a["first_step_ms"] for a in answers if a["first_step_ms"] is not None]
    est = [e for a in answers if (e := estimate_e2e(a, tier_p50_ms)) is not None]
    return {
        "count": len(answers),  # not "answers": the summary drops that key as per-row detail
        "degraded_left_out": len(every) - len(answers),
        "cost_mean_usd": _usd(_mean(costs)),
        "cost_p95_usd": _usd(percentile(costs, 95)),
        "latency_measured": len(e2e),
        "latency_p50_s": _s(percentile(e2e, 50)) if len(e2e) == len(answers) else None,
        "latency_p95_s": _s(percentile(e2e, 95)) if len(e2e) == len(answers) else None,
        "latency_p50_s_measured_only": _s(percentile(e2e, 50)),
        # Not gated: unmeasured calls counted at their tier's measured median (docs/09 §10f).
        "latency_estimated_p50_s": _s(percentile(est, 50)) if len(est) == len(answers) else None,
        "latency_estimated_p95_s": _s(percentile(est, 95)) if len(est) == len(answers) else None,
        "first_step_p95_s": _s(percentile(first, 95)) if len(first) == len(answers) else None,
    }


def _tiers(answers: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    n = len(answers) or 1
    for tier in TIER_GATES:
        calls = [c for a in answers for c in a["calls"] if c["tier"] == tier]
        lat = [c["latency_ms"] for c in calls if c["latency_ms"] is not None]
        cost = [c["cost_usd"] for c in calls if c["cost_usd"] is not None]
        out[tier] = {
            "models": sorted({c["model"] for c in calls}),
            "calls": len(calls),
            "latency_measured": len(lat),
            "call_latency_p50_s": _s(percentile(lat, 50)),
            "call_latency_p95_s": _s(percentile(lat, 95)),
            "cost_per_call_usd": _usd(_mean(cost)),
            "cost_per_answer_usd": _usd(sum(cost) / n) if cost else None,
            "accuracy_gates": list(TIER_GATES[tier]),
        }
    return out


def run(fast: bool = False, cases: Any = None) -> dict[str, Any]:
    rows = read_jsonl(cases or ui.CASES)
    if fast:
        rows = rows[:8]
    composed = ui.composition(rows, eval_model_client())
    if composed is None:
        return {
            "metrics": {"mode": eval_mode(), "answers": "not measured: needs DATABASE_URL"},
            "targets": [],
            "notes": ["E-EFF needs whole answers (DATABASE_URL, PostgreSQL)."],
        }
    answers = composed["answers"]
    clean = [a for a in answers if not a["degraded"]]
    tiers = _tiers(clean)
    p50 = {t: v["call_latency_p50_s"] * 1000 for t, v in tiers.items()
           if v["call_latency_p50_s"] is not None}  # fmt: skip
    groups = {
        "all": _group(answers, p50),
        "simple": _group([a for a in answers if a["kind"] == "simple"], p50),
        "advice": _group([a for a in answers if a["kind"] == "advice"], p50),
    }
    metrics: dict[str, Any] = {
        "mode": eval_mode(),
        "by_answer_type": groups,
        "by_tier": tiers,
        "answers": answers,
    }
    a, s, adv = groups["all"], groups["simple"], groups["advice"]
    n = f"{a['count']} E-UI answers"
    targets: list[Target] = [
        target("EFF-1", "Mean cost per answer (USD)", a["cost_mean_usd"], "<=", 0.03, n,
               stage1=False),
        target("EFF-2", "Mean cost per advice answer (USD)", adv["cost_mean_usd"], "<=", 0.055,
               f"{adv['count']} advice answers", stage1=False),
        target("EFF-3", "p95 cost per answer (USD)", a["cost_p95_usd"], "<=", 0.10, n,
               stage1=False),
        target("EFF-4", "Time to first progress step, p95 (s)", a["first_step_p95_s"], "<=", 2.0,
               n, stage1=False),
        target("EFF-5", "Simple answer latency p50 (s)", s["latency_p50_s"], "<=", 10.0,
               f"{s['count']} simple answers", stage1=False),
        target("EFF-6", "Advice answer latency p50 (s)", adv["latency_p50_s"], "<=", 35.0,
               f"{adv['count']} advice answers", stage1=False),
        target("EFF-7", "Advice answer latency p95 (s)", adv["latency_p95_s"], "<=", 60.0,
               f"{adv['count']} advice answers", stage1=False),
    ]  # fmt: skip
    notes = [
        f"{eval_mode()} mode. Latency is measured only in replay, from the live latency each "
        "cassette stores; an answer with an older recording (no latency) leaves its group's "
        f"latency not measured. Latency measured on {a['latency_measured']} of {a['count']} "
        f"answers. {len(answers) - len(clean)} answers with a failed or unrecorded model step "
        "are left out of every statistic.",
        "Where latency is not measured, `latency_estimated_*` counts each unmeasured call at its "
        "tier's measured median call latency; it is an estimate and decides no target.",
        "End-to-end = local time in replay + each step's model wait (concurrent judge calls "
        "overlap) − the Understand/prefetch overlap. Network and server time outside model calls "
        "are not included.",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
