"""Home's proactive insights (review R2, docs/01 PRO-01).

`GET /api/home/insights` reads, for the session's own profile only: the open deterministic
findings (every figure filled from its stored calculation, never model text), the checked
recommendations of the latest proactive run, and that run's state. `POST /api/home/check`
starts a proactive check now (a demo copy's "Run the proactive check"), within the profile's
daily allowance.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select

from backend.app import network_cap, proactive, views
from backend.app.session import Profile, read_only
from backend.app.ui_contracts.blocks import InterventionCard
from backend.app.ui_contracts.response import HomeInsights, InsightFinding
from backend.settings import get_settings
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext

router = APIRouter(prefix="/api/home", tags=["home"])

MAX_FINDINGS = 5
_SEVERITY_ORDER = {"act": 0, "watch": 1, "info": 2}


def _findings(ctx: WorkspaceContext) -> list[InsightFinding]:
    rows = ctx.session.scalars(
        ctx.select(m.Finding).where(m.Finding.status.in_(("candidate", "open")))
    ).all()
    rows = sorted(rows, key=lambda r: (_SEVERITY_ORDER.get(r.severity, 3), -(r.score or 0)))
    out = []
    for row in rows:
        headline = views.finding_text(row.headline, ctx)
        detail = views.finding_text(row.detail, ctx) if row.detail else ""
        if not headline or detail is None:
            continue
        out.append(
            InsightFinding(
                finding_id=row.id,
                kind=row.kind,
                severity=row.severity if row.severity in _SEVERITY_ORDER else "info",  # type: ignore[arg-type]
                headline=headline,
                detail=detail,
                link=views.finding_link(row.txn_query or {}),
            )
        )
        if len(out) == MAX_FINDINGS:
            break
    return out


def _cards(ctx: WorkspaceContext, run_id: str) -> list[InterventionCard]:
    recs = ctx.session.scalars(
        ctx.select(m.Recommendation).where(
            m.Recommendation.run_id == run_id, m.Recommendation.status == "approved"
        )
    ).all()
    cards = []
    for rec in recs:
        card = (rec.proposal or {}).get("card")
        try:
            if card:
                cards.append(InterventionCard.model_validate(card))
        except ValidationError:  # a card that can't be shown faithfully is left out, not guessed
            continue
    return cards[:2]


def insights(ctx: WorkspaceContext) -> HomeInsights:
    ws = ctx.workspace
    jobs = ctx.session.scalars(
        select(m.AnalysisJob)
        .where(m.AnalysisJob.workspace_id == ws.id)
        .order_by(m.AnalysisJob.created_at.desc())
        .limit(10)
    ).all()
    latest = jobs[0] if jobs else None
    ran = next((j for j in jobs if j.status == "done" and j.run_id), None)
    run = ctx.session.get(m.AgentRun, ran.run_id) if ran and ran.run_id else None
    blocked = proactive.advice_blocked(ctx.session, ws)

    reason: str | None = None
    if latest is None:
        state = "empty"
        reason = "not_run"
    elif latest.status in ("queued", "running"):
        state = "checking"
    elif latest.status == "failed":
        state = "failed"
    elif latest.status == "skipped" and latest.note == "manual_only":
        state = "empty"  # a demo edit: findings refreshed, advice waits for the button
        reason = "not_run"
    elif latest.status == "skipped":
        state = "paused"
        reason = latest.note if latest.note in ("ai_paused", "daily_limit") else None
    else:
        state = "ready"
    # Advice is shown only for the data and buffer it was checked against: after a newer change
    # it would describe a ledger or a threshold that no longer holds.
    cards = (
        _cards(ctx, run.id)
        if run
        and run.data_version == int(ws.data_version or 0)
        and run.prefs_version == ctx.prefs_version()  # checked against the current buffer
        else []
    )
    return HomeInsights(
        workspace_id=ws.id,
        status=state,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
        data_version=int(ws.data_version or 0),
        checked_data_version=run.data_version if run else None,
        checked_at=ran.finished_at if ran else None,
        findings=_findings(ctx),
        recommendations=cards,
        run_id=run.id if cards and run else None,
        can_check=blocked is None and state != "checking",
    )


@router.get("/insights", response_model=HomeInsights)
def get_insights(ctx: Profile) -> HomeInsights:
    return insights(ctx)


@router.post("/check", response_model=HomeInsights, status_code=status.HTTP_202_ACCEPTED)
def check_now(request: Request, ctx: Profile) -> HomeInsights:
    """Start a proactive check now (counts against the profile's daily allowance)."""
    if read_only(ctx.workspace):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This profile is read-only.")
    blocked = proactive.advice_blocked(ctx.session, ctx.workspace)
    if blocked == "ai_paused":
        raise HTTPException(status.HTTP_409_CONFLICT, "AI checks are paused right now.")
    if blocked == "daily_limit":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This profile has used today's proactive checks."
        )
    # A second request (another tab) while this profile's manual check waits joins it and
    # counts nothing; an automatic job queued by an edit becomes a manual check here, so that
    # one counts (#59 review). The row lock keeps two requests from both counting.
    ctx.session.execute(
        select(m.Workspace.id).where(m.Workspace.id == ctx.workspace_id).with_for_update()
    )
    if proactive.manual_check_queued(ctx):
        # Joins the profile's counted manual check (queued to run now, or just claimed by the
        # worker); nothing new is queued, so no second workflow can run uncounted (#59 review).
        ctx.session.commit()  # releases the row lock
        return insights(ctx)
    if proactive.advice_blocked(ctx.session, ctx.workspace) == "daily_limit":
        # A manual check may have finished between the first look and the lock: it used the
        # profile's day, so nothing is counted for one that would only be skipped (#59 review).
        ctx.session.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This profile has used today's proactive checks."
        )
    # A guest's checks also count per network, which a fresh guest profile doesn't reset.
    counted = ctx.workspace.owner_user_id is None
    if counted and not network_cap.allowance.take(
        request, "check", get_settings().guest_network_daily_checks
    ):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, network_cap.REFUSED)
    try:
        # An import whose ingestion hasn't run yet (skipped for a guest, or just claimed) gets
        # it from this check, so its rows aren't left without the ledger step (#59 review).
        workflow = "ingestion" if proactive.ingestion_owed(ctx) else None
        proactive.enqueue(ctx, "manual_check", immediate=True, workflow=workflow)
        ctx.session.commit()
    except Exception:
        if counted:  # no check was queued: the network's use is given back (#59 review)
            network_cap.allowance.give_back(request, "check")
        raise
    return insights(ctx)
