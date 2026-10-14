"""Specialist node slots (docs/06 §4.1–4.5). Each is filled by its own Stage 2 task.

Until a task lands, its slot records an honest `skipped` step ("not built yet", with the task id)
and changes nothing in the state: no placeholder findings, forecasts or advice are ever produced.
The advice loop's control nodes (`decide_after_verify`, `withdraw`) are real: they bound the loop
at two revisions (docs/06 §1 rule 4, W4).
"""

from __future__ import annotations

from backend.agents import ledger_nodes
from backend.agents.runtime import DEADLINES, NodeOutput, NodeSpec, RunContext
from backend.agents.state import ForesightState

MAX_REVISIONS = 2  # initial proposal + 2 revisions = 3 Verifier rounds (docs/06 W4)
# docs/06 §13 latency budget for a question (75 s deadline since 14 Oct 2026): one revision round
# is an Advisor call plus its concurrent judge calls; composing and saving the answer follows.
REVISION_ROUND_MS = 25_000
ANSWER_TAIL_MS = 5_000


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


WITHDRAW_LABELS = {
    ("deadline", False): "No recommendation was checked in time",
    ("deadline", True): "Out of time: the other drafts were not checked",
    ("revision_cap", False): "No recommendation passed the checks",
    ("revision_cap", True): "The other drafts didn't pass the checks",
    ("answered_with_approved", True): "A checked recommendation is ready; other drafts dropped",
}


def withdraw(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """The cap was reached, or the run ran out of time, with no approval: nothing is shown; history
    stays in the audit trail. Deterministic, so it also runs after the deadline."""
    proposals = list(state.get("proposals") or [])
    keys = [str(p.get("proposal_key", i)) for i, p in enumerate(proposals)]
    approved = bool(state.get("approved_recs"))
    if state.get("partial"):
        reason = "deadline"
    elif approved and state.get("workflow") == "conversation":
        reason = "answered_with_approved"
    else:
        reason = "revision_cap"
    with ctx.lock:
        for p in proposals:
            rec_id = p.get("rec_id")
            if rec_id and ctx.store.recommendation(rec_id) is not None:
                ctx.store.set_recommendation_status(rec_id, "withdrawn")
                ctx.store.ctx.append_audit(
                    "recommendation_withdrawn",
                    "recommendation",
                    rec_id,
                    actor="agent:coordinator",
                    after={"reason": reason},
                    run_id=ctx.run_id,
                )
    return NodeOutput(
        update={"withdrawn": keys, "proposals": [], "verdict": "none"},
        output={
            "withdrawn": keys,
            "rounds": int(state.get("revision_round") or 0) + 1,
            "reason": reason,
        },
        label=WITHDRAW_LABELS[(reason, approved)],
    )


def defer(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """A rejected round with revisions left but no time for one inside the question: the drafts
    stay in review (never shown) and the answer says a checked recommendation is on its way; the
    API starts an `advice_followup` run once the answer is saved."""
    proposals = list(state.get("proposals") or [])
    keys = [str(p.get("proposal_key", i)) for i, p in enumerate(proposals)]
    return NodeOutput(
        update={"followup_pending": True, "verdict": "none"},
        output={"deferred": keys, "rounds": int(state.get("revision_round") or 0) + 1},
        label="Checking a recommendation after the answer",
    )


def revision_fits(ctx: RunContext | None) -> bool:
    """A question's revision round starts only if it can finish inside the run deadline: the
    model wait so far plus one Advisor call and its judge calls, plus composing the answer.
    Uses recorded model wait, not the wall clock, so live, record and replay take one path."""
    if ctx is None or ctx.workflow != "conversation":
        return True
    deadline_ms = DEADLINES["conversation"].total_seconds() * 1000
    return ctx.waited_ms + REVISION_ROUND_MS + ANSWER_TAIL_MS <= deadline_ms


def decide_after_verify(state: ForesightState, ctx: RunContext | None = None) -> str:
    """W4 edge: approve/none → leave the loop; reject → revise (≤ 2, and in a question only while
    a round still fits in its deadline), defer (a question out of time: a follow-up run carries
    on) or withdraw (no revisions left)."""
    if state.get("partial") and state.get("proposals"):
        # Out of time (or budget) with drafts still unchecked: withdraw them, never leave them
        # in review and never loop.
        return "withdraw"
    if state.get("verdict") != "reject":
        return "leave"
    if state.get("partial"):
        # The run deadline or budget stopped work: nodes are being skipped, so a revision round
        # would never complete. Withdraw instead of looping (nothing unchecked is shown).
        return "withdraw"
    if state.get("workflow") == "conversation" and state.get("approved_recs"):
        # A question already has a checked recommendation: answer with it rather than spend
        # another Advisor and judge round on the drafts that failed (owner, 14 Oct 2026; the
        # first live run that kept revising took 82 s and $0.11).
        return "withdraw"
    if int(state.get("revision_round") or 0) < MAX_REVISIONS:
        if revision_fits(ctx):
            return "revise"
        # A question with revisions left but no time for one: answer now and carry the loop on
        # in a follow-up run (docs/06 §13) rather than dropping the advice.
        return "defer"
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
    from backend.agents import core_loop  # imports this module's names: import lazily

    return {
        spec.name: spec
        for spec in (
            ledger_nodes.nodes()["ledger"],
            ledger_nodes.nodes()["ledger_query"],
            ledger_nodes.nodes()["analyst"],
            *core_loop.nodes().values(),
            NodeSpec("revise", "coordinator", "control", revise_marker, "Revising the draft"),
            NodeSpec("defer", "coordinator", "control", defer, "Checking after the answer"),
            NodeSpec(
                "withdraw",
                "coordinator",
                "control",
                withdraw,
                "Withdrawing the draft",
                on_deadline=withdraw,
            ),
            _slot("briefing", "coordinator", "tool", "PRO-01", "Updating the Home briefing"),
            _slot("compose", "coordinator", "llm", "AGT-10", "Composing the answer"),
            _slot("freshness_check", "coordinator", "tool", "PRO-03", "Checking data freshness"),
            _slot("select_content", "coordinator", "tool", "PRO-03", "Choosing the digest"),
            _slot("compose_digest", "coordinator", "llm", "PRO-03", "Writing the digest"),
            _slot("deliver", "coordinator", "tool", "PRO-03", "Sending the digest"),
        )
    }
