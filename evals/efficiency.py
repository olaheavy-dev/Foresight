"""Cost and latency of whole answers, from recorded Mesh calls (docs/09 E-EFF).

Latency is only ever measured from real calls: every cassette stores the live call's wall time,
and a replayed call reports it (`MeshResult.latency_measured`). An answer's end-to-end time is
the local time measured while it is replayed plus the model wait of each step
(`AgentStep.model_ms`, which already overlaps concurrent judge calls), less the overlap of the two
parallel opening branches (Understand runs while the forecast is prefetched). A call recorded
before latency was kept makes that answer's latency "not measured", never estimated.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from backend.mesh.mesh_client import MeshCallError, MeshResult
from backend.storage.agent_repo import AgentStore


class CallLog:
    """Wraps the eval Mesh client and keeps every call it returns (thread-safe)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self.calls: list[MeshResult] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _keep(self, results: Any) -> None:
        with self._lock:
            self.calls.extend(results)

    def structured(self, **kwargs: Any) -> Any:
        try:
            result = self._inner.structured(**kwargs)
        except MeshCallError as exc:
            self._keep(getattr(exc, "calls", ()))
            raise
        self._keep(result.calls)
        return result

    def complete(self, **kwargs: Any) -> Any:
        result = self._inner.complete(**kwargs)
        self._keep([result])
        return result

    def take(self) -> list[MeshResult]:
        with self._lock:
            out, self.calls = self.calls, []
        return out


def _ms(delta: Any) -> int:
    return int(delta.total_seconds() * 1000)


def answer_profile(
    store: AgentStore,
    run_id: str,
    *,
    started: datetime,
    wall_ms: int,
    calls: list[MeshResult],
    replayed: bool,
) -> dict[str, Any]:
    """Cost, end-to-end latency and time to the first progress step of one answered question."""
    steps = store.steps(run_id)
    model_steps = [s for s in steps if s.llm_calls]
    costs = [s.cost_estimate_usd for s in model_steps]
    measured = replayed and all(s.model_ms is not None for s in model_steps)
    by_node = {s.node: s for s in steps}
    overlap = 0
    if "prefetch" in by_node and "understand" in by_node:
        overlap = min(by_node["prefetch"].latency_ms, by_node["understand"].model_ms or 0)
    e2e = wall_ms + sum(s.model_ms or 0 for s in model_steps) - overlap if measured else None
    first = steps[0] if steps else None
    ttfs = None
    if first is not None and (not first.llm_calls or first.model_ms is not None) and replayed:
        ttfs = max(0, _ms(first.finished_at - started)) + (first.model_ms or 0)
    return {
        "kind": "advice" if "advise" in by_node else "simple",
        # A model step failed (or its call was not recorded): its time and cost are not the
        # answer's real ones, so the answer is reported but left out of the statistics.
        "degraded": any(s.kind == "llm" and s.status == "failed" for s in steps),
        "failed_steps": [
            f"{s.node}: {(s.error or '')[:80]}"
            for s in steps
            if s.kind == "llm" and s.status == "failed"
        ],
        "cost_usd": None if any(c is None for c in costs) else round(sum(costs), 6),  # type: ignore[arg-type]
        "e2e_ms": e2e,
        # For the estimate when some calls have no recorded latency (see `estimate_e2e`).
        "wall_ms": wall_ms if replayed else None,
        "overlap_ms": overlap,
        "steps": [
            {"node": s.node, "tier": s.tier, "llm_calls": s.llm_calls, "model_ms": s.model_ms}
            for s in model_steps
        ],
        "first_step_ms": ttfs,
        "model_calls": len(calls),
        "calls": [
            {
                "tier": c.tier,
                "model": c.model,
                "latency_ms": c.latency_ms if c.latency_measured else None,
                "cost_usd": c.cost_estimate,
            }
            for c in calls
        ],
    }


def estimate_e2e(answer: dict[str, Any], tier_p50_ms: dict[str, float]) -> int | None:
    """End-to-end estimate for an answer whose steps include calls recorded before latency was
    kept: each such step counts its calls at its tier's measured median. Reported as an estimate,
    never gated; None when a needed median is missing."""
    if answer.get("e2e_ms") is not None:
        return int(answer["e2e_ms"])
    if answer.get("wall_ms") is None:
        return None
    total = answer["wall_ms"] - answer.get("overlap_ms", 0)
    for step in answer.get("steps") or []:
        if step["model_ms"] is not None:
            total += step["model_ms"]
        elif step["tier"] in tier_p50_ms:
            total += step["llm_calls"] * tier_p50_ms[step["tier"]]
        else:
            return None
    return int(total)
