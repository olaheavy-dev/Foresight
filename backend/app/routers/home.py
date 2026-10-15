"""Home's proactive insights (review R2, docs/01 PRO-01).

`GET /api/home/insights` reads, for the session's own profile only: the open deterministic
findings (every figure filled from its stored calculation, never model text), the checked
recommendations of the latest proactive run, and that run's state. `POST /api/home/check`
starts a proactive check now (a demo copy's "Run the proactive check"), within the profile's
daily allowance.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select

from backend.app import proactive, views
from backend.app.session import Profile, read_only
from backend.app.ui_contracts.blocks import InterventionCard
from backend.app.ui_contracts.money import money_value
from backend.app.ui_contracts.primitives import MoneyAmount
from backend.app.ui_contracts.response import HomeInsights, InsightFinding
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext

router = APIRouter(prefix="/api/home", tags=["home"])

MAX_FINDINGS = 5
_PLACEHOLDER = re.compile(r"\{\{\s*(calc_[0-9a-zA-Z]+)#([a-z_]+)\|([a-z_]+)\s*\}\}")
_SEVERITY_ORDER = {"act": 0, "watch": 1, "info": 2}


def _fill(text: str, ctx: WorkspaceContext) -> str | None:
    """Fill each `{{calc_…#path|format}}` from the stored calculation; None if any can't be
    (a finding is then left out rather than shown with a gap or a guessed number)."""
    missing = False

    def one(match: re.Match[str]) -> str:
        nonlocal missing
        calc_id, path, fmt = match.groups()
        calc = ctx.calculation(calc_id)
        result: dict[str, Any] = calc.result if calc is not None else {}
        value = result.get(path)
        if value is None:
            missing = True
            return ""
        if fmt == "money":
            currency = str(result.get("currency") or ctx.workspace.home_currency)
            amount = MoneyAmount(amount_minor=int(value), currency=currency)
            return money_value(amount, ctx.workspace.locale, "rounded").display
        if fmt == "pct_change":
            return f"{round(abs(float(value)) * 100)}%"
        if fmt == "count":
            return str(int(value))
        if fmt == "date":
            return views.short_date(date.fromisoformat(str(value)))
        missing = True
        return ""

    filled = _PLACEHOLDER.sub(one, text)
    return None if missing or "{{" in filled else filled


def _link(query: dict[str, Any]) -> str | None:
    if query.get("category"):
        return f"/transactions?category={query['category']}"
    if query.get("obligation_key") or query.get("obligation_keys"):
        return "/transactions?tab=recurring"
    return None


def _findings(ctx: WorkspaceContext) -> list[InsightFinding]:
    rows = ctx.session.scalars(
        ctx.select(m.Finding).where(m.Finding.status.in_(("candidate", "open")))
    ).all()
    rows = sorted(rows, key=lambda r: (_SEVERITY_ORDER.get(r.severity, 3), -(r.score or 0)))
    out = []
    for row in rows:
        headline = _fill(row.headline, ctx)
        detail = _fill(row.detail, ctx) if row.detail else ""
        if not headline or detail is None:
            continue
        out.append(
            InsightFinding(
                finding_id=row.id,
                kind=row.kind,
                severity=row.severity if row.severity in _SEVERITY_ORDER else "info",  # type: ignore[arg-type]
                headline=headline,
                detail=detail,
                link=_link(row.txn_query or {}),
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
    elif latest.status == "skipped":
        state = "paused"
        reason = latest.note if latest.note in ("ai_paused", "daily_limit") else None
    else:
        state = "ready"
    return HomeInsights(
        workspace_id=ws.id,
        status=state,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
        data_version=int(ws.data_version or 0),
        checked_data_version=run.data_version if run else None,
        checked_at=ran.finished_at if ran else None,
        findings=_findings(ctx),
        recommendations=_cards(ctx, run.id) if run else [],
        can_check=blocked is None and state != "checking",
    )


@router.get("/insights", response_model=HomeInsights)
def get_insights(ctx: Profile) -> HomeInsights:
    return insights(ctx)


@router.post("/check", response_model=HomeInsights, status_code=status.HTTP_202_ACCEPTED)
def check_now(ctx: Profile) -> HomeInsights:
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
    proactive.enqueue(ctx, "manual_check", immediate=True)
    ctx.session.commit()
    return insights(ctx)
