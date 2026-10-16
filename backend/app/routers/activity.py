"""Activity: the profile's agent runs as traces, and its audit log in words.

Traces stay in-house (docs/05): an `AgentRun` is a trace and its `AgentStep` rows are the spans.
This exposes their metadata only (agent, model, latency, tokens, cost, status, Verifier verdicts),
never a prompt or a model's output, and only for the session's own profile.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from backend.app.session import Profile
from backend.app.ui_contracts.response import (
    ActivityEvent,
    ActivityFeed,
    ActivityRun,
    ActivityStep,
)
from backend.storage import models as m

router = APIRouter(prefix="/api/activity", tags=["activity"])

PHRASES = {
    # One event per imported table (a file's pocket, or a month's file for the same account), so
    # the count is of tables, never of statements or accounts.
    "import.committed": ("Imported a table of transactions", "Imported {n} tables of transactions"),
    "import.needs_review": ("A statement is waiting for an answer", "{n} statements are waiting"),
    "txn.recategorised": (
        "Changed a transaction’s category",
        "Changed the category of {n} transactions",
    ),
    "forecast.rebuilt": ("Rebuilt the forecast", "Rebuilt the forecast {n} times"),
    "balance.declared": ("Added a balance", "Added {n} balances"),
    "profile.renamed": ("Renamed the profile", "Renamed the profile {n} times"),
    "profile.buffer_set": ("Changed the buffer", "Changed the buffer {n} times"),
    "recommendation_approved": (
        "A recommendation passed the Verifier’s checks",
        "{n} recommendations passed the Verifier’s checks",
    ),
    "recommendation_withdrawn": (
        "A draft recommendation was withdrawn",
        "{n} draft recommendations were withdrawn",
    ),
    "input_refused": ("Refused an unsafe request", "Refused {n} unsafe requests"),
    "run_budget_exceeded": ("A run stopped at its spending limit", "{n} runs stopped at limits"),
    "prompt_leak_blocked": ("Blocked an answer that broke the rules", "Blocked {n} answers"),
    "output_screen_blocked": ("Blocked an answer that broke the rules", "Blocked {n} answers"),
}
INCOME = {
    "confirmed": "Confirmed an income stream",
    "rejected": "Marked a payment as not income",
    "detected": "Undid an income decision",
}


def _summary(action: str, count: int, after: dict[str, Any] | None) -> str:
    if action == "income_decision":
        return INCOME.get(str((after or {}).get("provenance")), "Changed an income decision")
    one, many = PHRASES.get(action, (action.replace(".", " ").replace("_", " ").capitalize(), ""))
    return many.format(n=count) if count > 1 and many else one


def _events(ctx: Any, limit: int) -> list[ActivityEvent]:
    """Newest first. Consecutive identical actions collapse into one line, except corrections:
    those collapse only within one batch (one correction applied to every payment from a payee),
    so two separate corrections stay two lines."""
    rows = ctx.session.scalars(
        ctx.select(m.AuditEvent).order_by(m.AuditEvent.seq.desc()).limit(limit * 20)
    ).all()
    out: list[ActivityEvent] = []
    group: list[m.AuditEvent] = []

    def flush() -> None:
        if group:
            head = group[0]
            out.append(
                ActivityEvent(
                    seq=head.seq,
                    occurred_at=head.occurred_at,
                    actor=head.actor or "system",
                    action=head.action,
                    summary=_summary(head.action, len(group), head.after),
                )
            )
            group.clear()

    for row in rows:
        same = group and row.action == group[0].action and row.actor == group[0].actor
        if same and row.action == "txn.recategorised":
            batch = (row.after or {}).get("batch")
            same = batch is not None and batch == (group[0].after or {}).get("batch")
        if group and (not same or row.action == "income_decision"):
            flush()
        group.append(row)
        if len(out) >= limit:
            break
    flush()
    return out[:limit]


@router.get("", response_model=ActivityFeed)
def activity(ctx: Profile, limit: int = Query(default=20, ge=1, le=50)) -> ActivityFeed:
    runs = ctx.session.scalars(
        ctx.select(m.AgentRun).order_by(m.AgentRun.started_at.desc()).limit(limit)
    ).all()
    run_ids = [r.id for r in runs]
    steps: dict[str, list[m.AgentStep]] = {rid: [] for rid in run_ids}
    verdicts: dict[str, dict[str, int]] = {rid: {"APPROVE": 0, "REJECT": 0} for rid in run_ids}
    questions: dict[str, str] = {}
    if run_ids:
        for step in ctx.session.scalars(
            ctx.select(m.AgentStep)
            .where(m.AgentStep.run_id.in_(run_ids))
            .order_by(m.AgentStep.run_id, m.AgentStep.seq)
        ):
            steps[step.run_id].append(step)
        for run_id, verdict, n in ctx.session.execute(
            select(m.VerificationResult.run_id, m.VerificationResult.verdict, func.count())
            .where(
                m.VerificationResult.workspace_id == ctx.workspace_id,
                m.VerificationResult.run_id.in_(run_ids),
            )
            .group_by(m.VerificationResult.run_id, m.VerificationResult.verdict)
        ):
            verdicts[run_id][verdict] = int(n)
        for msg in ctx.session.scalars(
            ctx.select(m.Message).where(m.Message.run_id.in_(run_ids), m.Message.role == "user")
        ):
            if msg.run_id:  # the person's own words: the model's standalone rewrite could carry
                # a figure the model wrote, and no model figure is shown unchecked (rule 2)
                questions[msg.run_id] = (msg.text or "")[:300]

    total = ctx.session.scalar(
        select(func.count())
        .select_from(m.AuditEvent)
        .where(m.AuditEvent.workspace_id == ctx.workspace_id)
    )
    return ActivityFeed(
        workspace_id=ctx.workspace_id,
        runs=[
            ActivityRun(
                run_id=r.id,
                workflow=r.workflow,
                trigger=r.trigger,
                status=r.status,
                partial=bool(r.partial),
                question=questions.get(r.id),
                started_at=r.started_at,
                duration_ms=(
                    int((r.finished_at - r.started_at).total_seconds() * 1000)
                    if r.finished_at
                    else None
                ),
                llm_calls=r.llm_calls or 0,
                tokens_in=r.tokens_in or 0,
                tokens_out=r.tokens_out or 0,
                cost_usd=r.cost_estimate_usd,
                revisions=r.revision_count or 0,
                approved=verdicts[r.id]["APPROVE"],
                rejected=verdicts[r.id]["REJECT"],
                steps=[
                    ActivityStep(
                        seq=s.seq,
                        node=s.node,
                        agent=s.agent,
                        kind=s.kind,
                        label=s.label or "",
                        model=s.model,  # e.g. anthropic/claude-sonnet-5.5, behind Mesh
                        status=s.status,
                        cached=bool(s.cached),
                        latency_ms=s.latency_ms,
                        tokens_in=s.tokens_in or 0,
                        tokens_out=s.tokens_out or 0,
                        cost_usd=s.cost_estimate_usd,
                    )
                    for s in steps[r.id]
                ],
            )
            for r in runs
        ],
        events=_events(ctx, limit=40),
        audit_events=int(total or 0),
        audit_chain_intact=ctx.audit_chain_valid(),
    )
