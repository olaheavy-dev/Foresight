"""Specialist node slots (docs/06 §4.1–4.5). Each is filled by its own Stage 2 task.

Until a task lands, its slot records an honest `skipped` step ("not built yet", with the task id)
and changes nothing in the state: no placeholder findings, forecasts or advice are ever produced.
The advice loop's control nodes (`decide_after_verify`, `withdraw`) are real: they bound the loop
at two revisions (docs/06 §1 rule 4, W4).
"""

from __future__ import annotations

from backend.agents import ledger_nodes
from backend.agents.runtime import NodeOutput, NodeSpec, RunContext
from backend.agents.state import ForesightState

MAX_REVISIONS = 2  # initial proposal + 2 revisions = 3 Verifier rounds (docs/06 W4)


def not_built(task: str, what: str) -> NodeOutput:
    return NodeOutput(
        status="skipped",
        output={"reason": "not built yet", "task": task},
        label=f"{what}: not built yet",
    )


def _slot(name: str, agent: str, kind: str, task: str, label: str) -> NodeSpec:
    def fn(state: ForesightState, ctx: RunContext) -> NodeOutput:
        return not_built(task, label)

    fn.__name__ = name
    return NodeSpec(name=name, agent=agent, kind=kind, fn=fn, label=label)


def withdraw(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """The cap was reached with no approval: nothing is shown; history stays in the audit trail."""
    keys = [str(p.get("proposal_key", i)) for i, p in enumerate(state.get("proposals") or [])]
    return NodeOutput(
        update={"withdrawn": keys, "proposals": [], "verdict": "none"},
        output={"withdrawn": keys, "rounds": int(state.get("revision_round") or 0) + 1},
        label="No recommendation passed the checks",
    )


def decide_after_verify(state: ForesightState) -> str:
    """W4 edge: approve/none → leave the loop; reject → revise (≤ 2) or withdraw."""
    if state.get("verdict") != "reject":
        return "leave"
    if int(state.get("revision_round") or 0) < MAX_REVISIONS:
        return "revise"
    return "withdraw"


def revise_marker(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """Counts a revision round before the Advisor runs again with the Verifier's critique."""
    round_ = int(state.get("revision_round") or 0) + 1
    return NodeOutput(
        update={"revision_round": round_, "verdict": None},
        output={"revision_round": round_},
        label="Verifier rejected a draft; revising",
    )


def specialist_nodes() -> dict[str, NodeSpec]:
    return {
        spec.name: spec
        for spec in (
            ledger_nodes.nodes()["ledger"],
            ledger_nodes.nodes()["ledger_query"],
            ledger_nodes.nodes()["analyst"],
            _slot("forecaster", "forecaster", "llm", "AGT-05", "Building the forecast"),
            _slot("risk_check", "forecaster", "tool", "AGT-05", "Checking for risks"),
            _slot("advise", "advisor", "llm", "AGT-06", "Drafting a recommendation"),
            _slot("verify", "verifier", "llm", "AGT-07", "Checking the recommendation"),
            NodeSpec("revise", "coordinator", "control", revise_marker, "Revising the draft"),
            NodeSpec("withdraw", "coordinator", "control", withdraw, "Withdrawing the draft"),
            _slot("briefing", "coordinator", "tool", "PRO-01", "Updating the Home briefing"),
            _slot("compose", "coordinator", "llm", "AGT-10", "Composing the answer"),
            _slot("freshness_check", "coordinator", "tool", "PRO-03", "Checking data freshness"),
            _slot("select_content", "coordinator", "tool", "PRO-03", "Choosing the digest"),
            _slot("compose_digest", "coordinator", "llm", "PRO-03", "Writing the digest"),
            _slot("deliver", "coordinator", "tool", "PRO-03", "Sending the digest"),
        )
    }
