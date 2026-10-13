"""LangGraph graphs for the six workflows (docs/06 §8).

One builder serves every workflow. The Coordinator puts the specialists to run in `state["route"]`
(from the route tables, docs/06 §6); a dispatcher edge walks that list, so the topology is fixed and
inspectable while each run only executes what its route needs. `advice_loop` in a route expands to
the bounded Advisor ⇄ Verifier loop (W4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents import coordinator as c
from backend.agents.runtime import NodeSpec, RunContext, instrument
from backend.agents.specialists import decide_after_verify, specialist_nodes
from backend.agents.state import ForesightState

ADVICE_LOOP = "advice_loop"
TAIL = {"conversation": "compose"}  # conversation answers always end in compose → persist


def coordinator_nodes() -> dict[str, NodeSpec]:
    return {
        spec.name: spec
        for spec in (
            NodeSpec("route_event", "coordinator", "control", c.route_event, "Planning the work"),
            NodeSpec("intake", "coordinator", "control", c.intake, "Reading your question"),
            NodeSpec("prefetch", "coordinator", "tool", c.prefetch, "Loading your forecast"),
            NodeSpec("understand", "coordinator", "llm", c.understand, "Understanding"),
            NodeSpec("triage", "coordinator", "control", c.triage, "Deciding how to answer"),
            NodeSpec("refuse", "coordinator", "control", c.refuse, "Out of scope"),
            NodeSpec("clarify", "coordinator", "control", c.clarify, "Asking to clarify"),
            NodeSpec("cache_lookup", "coordinator", "tool", c.cache_lookup, "Checking answers"),
            NodeSpec(
                "persist_response",
                "coordinator",
                "tool",
                c.persist_response,
                "Answer ready",
                on_deadline=c.persist_response,
            ),
        )
    }


def composer_nodes() -> dict[str, NodeSpec]:
    from backend.agents.compose import compose

    return {
        "compose": NodeSpec(
            "compose", "coordinator", "llm", compose, "Composing the answer", on_deadline=compose
        )
    }


def default_nodes() -> dict[str, NodeSpec]:
    return {**coordinator_nodes(), **specialist_nodes(), **composer_nodes()}


def _next_after(current: str | None, state: ForesightState) -> str:
    """The next node on the run's route after `current` (None = start of the route)."""
    route = list(state.get("route") or [])
    index = 0 if current is None else route.index(current) + 1 if current in route else len(route)
    while index < len(route):
        step = route[index]
        if step == ADVICE_LOOP:
            # System workflows run advice only when a risk or finding asked for it.
            if state.get("workflow") == "conversation" or state.get("risk_flags"):
                return "advise"
            index += 1
            continue
        return step
    tail = TAIL.get(str(state.get("workflow")))
    if tail and current != tail:
        return tail
    return "persist_response" if state.get("workflow") == "conversation" else END


def build_graph(
    workflow: str,
    ctx: RunContext,
    *,
    nodes: Mapping[str, NodeSpec] | None = None,
    checkpointer: Any = None,
) -> Any:
    specs = {**default_nodes(), **(nodes or {})}
    graph: StateGraph[ForesightState] = StateGraph(ForesightState)
    for spec in specs.values():
        graph.add_node(spec.name, instrument(spec, ctx))  # type: ignore[call-overload]

    route_steps = [
        n
        for n in specs
        if n
        not in {
            "route_event",
            "intake",
            "prefetch",
            "understand",
            "triage",
            "refuse",
            "clarify",
            "cache_lookup",
            "persist_response",
            "verify",
            "revise",
            "withdraw",
        }
    ]
    targets = [*route_steps, "persist_response", END]

    def dispatch_from(current: str | None) -> Any:
        def edge(state: ForesightState) -> str:
            return _next_after(current, state)

        return edge

    if workflow == "conversation":
        graph.add_edge(START, "intake")
        graph.add_edge("intake", "prefetch")
        graph.add_edge("intake", "understand")
        graph.add_edge(["prefetch", "understand"], "triage")
        graph.add_conditional_edges(
            "triage",
            c.triage_decision,
            ["refuse", "clarify", "cache_lookup", "persist_response"],
        )
        graph.add_edge("refuse", "persist_response")
        graph.add_edge("clarify", "persist_response")
        graph.add_conditional_edges(
            "cache_lookup",
            lambda s: "persist_response" if s.get("cache_hit") else _next_after(None, s),
            targets,
        )
        graph.add_edge("persist_response", END)
    else:
        graph.add_edge(START, "route_event")
        graph.add_conditional_edges("route_event", dispatch_from(None), targets)
        for name in (
            "intake",
            "prefetch",
            "understand",
            "triage",
            "refuse",
            "clarify",
            "cache_lookup",
        ):
            graph.add_edge(name, END)  # present in the topology, unreachable here
        graph.add_edge("persist_response", END)

    for name in route_steps:
        if name == "advise":
            continue
        graph.add_conditional_edges(name, dispatch_from(name), targets)

    # W4: advise → verify → leave | revise → advise | withdraw → leave.
    graph.add_edge("advise", "verify")
    graph.add_edge("revise", "advise")

    def after_loop(state: ForesightState) -> str:
        return _next_after(ADVICE_LOOP, state)

    graph.add_conditional_edges(
        "verify",
        lambda s: (
            "revise"
            if decide_after_verify(s) == "revise"
            else "withdraw"
            if decide_after_verify(s) == "withdraw"
            else after_loop(s)
        ),
        ["revise", "withdraw", *targets],
    )
    graph.add_conditional_edges("withdraw", after_loop, targets)
    return graph.compile(checkpointer=checkpointer)
