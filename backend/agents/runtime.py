"""What every agent node runs inside (docs/06 §1 rules 4–5, §10, §11; docs/05 §6.4).

A node is a plain function `(state, ctx) -> NodeOutput`. `instrument()` turns it into a LangGraph
node that:

- skips it when the run deadline has passed (the run becomes `partial`);
- refuses model work once the run budget is used (docs/01 FR-60), with an audit event;
- writes exactly one `AgentStep` for it: timing, model wait (`model_ms`), status, model, tokens,
  cost (provider `usage` × the price table, never model text), temperature sent ("model default" =
  None), templated label;
- turns a model-call failure into a recorded, degraded step (docs/06 §10.1), while any other
  exception fails the run loudly: no fabricated fallback numbers.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.agents.budget import Budget, BudgetExceeded
from backend.agents.state import ForesightState
from backend.llm.client import ModelCallError, ModelClient, ModelResult
from backend.storage.agent_repo import AgentStore

# docs/05 §6.4: run deadlines.
DEADLINES = {
    "conversation": timedelta(seconds=75),  # owner, 14 Oct 2026 (was 60 s)
    "ingestion": timedelta(seconds=120),
}
DEFAULT_DEADLINE = timedelta(seconds=120)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class NodeOutput:
    """What a node returns. `update` goes into the graph state; the rest into its AgentStep."""

    update: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | retried | failed | skipped
    label: str | None = None  # templated user-facing label (never model text)
    llm: Sequence[ModelResult] = ()
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    prompt_version: str | None = None
    cached: bool = False
    error: str | None = None
    # Model wait on the step's critical path when its calls overlapped (see `concurrent_ms`);
    # None = the calls ran one after another, so their latencies add up.
    model_ms: int | None = None


def model_ms(results: Sequence[ModelResult]) -> int | None:
    """Model wait of calls made one after another; None if any latency was not measured."""
    if not results or any(not r.latency_measured for r in results):
        return None
    return sum(r.latency_ms for r in results)


def concurrent_ms(groups: Sequence[Sequence[ModelResult]], workers: int) -> int | None:
    """Model wait of call groups run on a pool of `workers` threads, each group's calls in turn:
    groups start in order on the first free worker (as `ThreadPoolExecutor.map` does), and the
    wait is when the busiest worker finishes."""
    lanes = [0] * max(1, workers)
    for group in groups:
        if not group:
            continue
        ms = model_ms(group)
        if ms is None:
            return None
        free = lanes.index(min(lanes))
        lanes[free] += ms
    return max(lanes) if any(groups) else None


@dataclass
class RunContext:
    """Per-run services handed to every node. Not part of the (checkpointed) graph state."""

    store: AgentStore
    run_id: str
    workflow: str
    deadline_at: datetime
    model_client: ModelClient | None = None
    budget: Budget = field(default_factory=Budget)
    clock: Callable[[], datetime] = utcnow
    commit: bool = True  # commit after each step so SSE readers see progress
    lock: threading.RLock = field(default_factory=threading.RLock)
    # Every call charged in this run, in order: a step stopped by the budget still records the
    # calls it made before the refusal (they were paid for).
    charged: list[ModelResult] = field(default_factory=list)
    # Model wait so far on the run's critical path (sum of the steps' `model_ms`): the recorded
    # latencies, so a time-based decision is the same live, in record mode and in replay.
    waited_ms: int = 0

    def deadline_passed(self) -> bool:
        return self.clock() >= self.deadline_at

    def charge(self, results: Sequence[ModelResult]) -> None:
        self.budget.charge(len(results), sum(r.usage.total_tokens for r in results))
        self.charged.extend(results)

    def before_llm(self) -> None:
        """Call before each model call; raises BudgetExceeded when the run's budget is used."""
        self.budget.check()

    def require_model_client(self) -> ModelClient:
        if self.model_client is None:
            raise ModelCallError("no model client configured for this run")
        return self.model_client


NodeFn = Callable[[ForesightState, RunContext], NodeOutput]


@dataclass(frozen=True)
class NodeSpec:
    name: str
    agent: str  # coordinator | ledger | analyst | forecaster | advisor | verifier | system
    kind: str  # llm | tool | control
    fn: NodeFn
    label: str  # default templated label, e.g. "Building forecast"
    # Runs instead of skipping once the run deadline has passed: deterministic, no model calls
    # (withdraw, compose and persist, so a late run still ends with an answer, docs/05 §6.4).
    on_deadline: NodeFn | None = None


def _usage(results: Sequence[ModelResult], overlapped_ms: int | None = None) -> dict[str, Any]:
    tokens_in = sum(r.usage.prompt_tokens for r in results)
    tokens_out = sum(r.usage.completion_tokens for r in results)
    costs = [r.cost_estimate for r in results]
    cost = None if not results or any(c is None for c in costs) else round(sum(costs), 8)  # type: ignore[arg-type]
    last = results[-1] if results else None
    return {
        "llm_calls": len(results),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_estimate_usd": cost,
        "model": last.model if last else None,
        "tier": last.tier if last else None,
        "provider": last.provider if last else None,
        "temperature": last.temperature if last else None,
        "attempt": max((r.attempts for r in results), default=1),
        "model_ms": overlapped_ms if overlapped_ms is not None else model_ms(results),
    }


def _input_view(state: ForesightState) -> dict[str, Any]:
    """The part of the state a step's input hash covers (identity, versions, inputs, refs)."""
    keys = (
        "workflow",
        "trigger",
        "event",
        "data_version",
        "prefs_version",
        "as_of",
        "scope",
        "user_message",
        "intent",
        "route",
        "forecast_id",
        "findings",
        "proposals",
        "revision_round",
        "verdict",
        "cache_key",
    )
    return {k: state.get(k) for k in keys if k in state}


def write_step(
    ctx: RunContext,
    spec: NodeSpec,
    state: ForesightState,
    out: NodeOutput,
    started: datetime,
) -> None:
    usage = _usage(out.llm, out.model_ms)
    with ctx.lock:
        ctx.waited_ms += usage["model_ms"] or 0
        ctx.store.add_step(
            ctx.run_id,
            node=spec.name,
            agent=spec.agent,
            kind=spec.kind,
            prompt_version=out.prompt_version,
            input_hash=canonical_hash(_input_view(state)),
            output=out.output,
            tool_calls=out.tool_calls,
            latency_ms=int((ctx.clock() - started).total_seconds() * 1000),
            cached=out.cached,
            status=out.status,
            label=out.label or spec.label,
            error=out.error,
            started_at=started,
            finished_at=ctx.clock(),
            **usage,
        )
        if ctx.commit:
            ctx.store.session.commit()


def instrument(spec: NodeSpec, ctx: RunContext) -> Callable[[ForesightState], dict[str, Any]]:
    def node(state: ForesightState) -> dict[str, Any]:
        started = ctx.clock()
        if ctx.deadline_passed() and spec.on_deadline is not None:
            late: ForesightState = {**state, "partial": True}
            out = spec.on_deadline(late, ctx)
            out.update = {**out.update, "partial": True}
        elif ctx.deadline_passed():
            out = NodeOutput(
                status="skipped",
                label=f"{spec.label}: stopped, run deadline reached",
                output={"reason": "deadline"},
                update={"partial": True},
            )
        else:
            charged_before = len(ctx.charged)
            try:
                out = spec.fn(state, ctx)
            except BudgetExceeded as exc:
                with ctx.lock:
                    ctx.store.ctx.append_audit(
                        "run_budget_exceeded",
                        "agent_run",
                        ctx.run_id,
                        actor=f"agent:{spec.agent}",
                        after={"node": spec.name, "detail": str(exc)},
                        run_id=ctx.run_id,
                    )
                out = NodeOutput(
                    llm=tuple(ctx.charged[charged_before:]),
                    status="skipped",
                    label=f"{spec.label}: model budget for this run used",
                    output={"reason": "budget", "detail": str(exc)},
                    update={"partial": True},
                    error=str(exc),
                )
            except ModelCallError as exc:
                # Degrade (docs/06 §10.1): record it, keep the deterministic parts going. Calls
                # made before a schema failure still count towards the budget and the cost.
                spent = tuple(getattr(exc, "calls", ()))
                ctx.charge(spent)
                out = NodeOutput(
                    llm=spent,
                    status="failed",
                    label=f"{spec.label}: AI explanation unavailable",
                    output={"reason": type(exc).__name__},
                    update={"errors": [{"node": spec.name, "error": type(exc).__name__}]},
                    error=str(exc),
                )
        write_step(ctx, spec, state, out, started)
        return out.update

    node.__name__ = spec.name
    return node


def deadline_for(workflow: str, now: datetime | None = None) -> datetime:
    return (now or utcnow()) + DEADLINES.get(workflow, DEFAULT_DEADLINE)
