"""Goals (docs/01 F-55, FR-69; docs/07 §6.7): save-by-date goals with `residual` funding, each
projected on the forecast's own paths and shown as the Workspace's GoalProjection block. Every
figure comes from the stored `goal_projection` calculation; nothing here computes one.

Goal edits are audited but leave `data_version` and `prefs_version` alone: a goal doesn't change
the ledger, and no advice is checked against goals yet (adaptive goal advice isn't shipped), so
there is nothing to make stale.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, status

from backend.app import views
from backend.app.session import Profile, read_only
from backend.app.ui_contracts.blocks import (
    FanSeries,
    GoalOutcome,
    GoalProjection,
    GoalSummary,
)
from backend.app.ui_contracts.money import money_value
from backend.app.ui_contracts.primitives import (
    DateValue,
    MoneyAmount,
    OverviewPlacement,
    PercentValue,
)
from backend.app.ui_contracts.response import GoalCreate, GoalList, GoalUpdate, GoalView
from backend.finance_core.goals import GoalError
from backend.pipeline.forecast import NoLedgerData, run_goal_projection
from backend.storage import models as m
from backend.storage.ids import new_id
from backend.storage.repositories import WorkspaceContext

router = APIRouter(prefix="/api/goals", tags=["goals"])

MAX_ACTIVE = 5


def _money(minor: int, currency: str, locale: str, ref: str | None = None) -> Any:
    return money_value(MoneyAmount(amount_minor=minor, currency=currency), locale, "exact", ref)


def _projection(ctx: WorkspaceContext, goal: m.Goal) -> tuple[GoalProjection, str, bool]:
    stored = run_goal_projection(ctx, goal)
    calc, r = stored.calculation.id, stored.result
    cur, loc = goal.currency, ctx.workspace.locale
    accounts = [
        a.id
        for a in ctx.all(m.Account)
        if a.include_in_forecast and a.tracked and a.currency == cur
    ]
    p = r["progress"]
    required = r["required_monthly_minor"]
    block = GoalProjection(
        type="GoalProjection",
        block_id=f"goal-{goal.id}",
        title=goal.name,
        currency=cur,
        placement=OverviewPlacement(area="overview", slot="main_visual"),
        evidence=[f"{calc}#progress.p50"],
        scope=views.forecast_scope(ctx, accounts),
        goal=GoalSummary(
            goal_id=goal.id,
            name=goal.name,
            target=_money(goal.target_minor, cur, loc, f"{calc}#goal.target_minor"),
            target_date=DateValue(
                kind="date", value=goal.target_date, display=views.short_date(goal.target_date)
            ),
            funding_rule="residual",
        ),
        progress_now=_money(r["progress_now_minor"], cur, loc, f"{calc}#progress_now_minor"),
        projection=GoalOutcome(
            p10=_money(p["p10"], cur, loc, f"{calc}#progress.p10"),
            p50=_money(p["p50"], cur, loc, f"{calc}#progress.p50"),
            p90=_money(p["p90"], cur, loc, f"{calc}#progress.p90"),
            p_achieve=PercentValue(
                kind="percent",
                value=r["p_achieve"],
                display=f"{round(r['p_achieve'] * 100)}%",
                ref=f"{calc}#p_achieve",
            ),
            status_band=r["status_band"],
        ),
        trajectory=FanSeries(
            dates=[date.fromisoformat(d) for d in r["trajectory_dates"]],
            p10=r["trajectory_p10"],
            p50=r["trajectory_p50"],
            p90=r["trajectory_p90"],
        ),
        required_monthly_change=(
            _money(required, cur, loc, f"{calc}#required_monthly_minor") if required else None
        ),
    )
    return block, calc, bool(r["lower_confidence"])


def _view(ctx: WorkspaceContext, goal: m.Goal) -> GoalView:
    view: dict[str, Any] = {
        "goal_id": goal.id,
        "name": goal.name,
        "status": goal.status,
        "target": _money(goal.target_minor, goal.currency, ctx.workspace.locale),
        "target_date": goal.target_date,
    }
    if goal.status != "active":
        return GoalView(**view)
    try:
        block, calc, lower = _projection(ctx, goal)
    except NoLedgerData:
        return GoalView(**view, problem="Import a statement first: a goal is projected on it.")
    except GoalError as exc:
        return GoalView(**view, problem=f"This goal can’t be projected: {exc}.")
    return GoalView(**view, projection=block, calc_id=calc, lower_confidence=lower)


def _goals(ctx: WorkspaceContext) -> list[m.Goal]:
    rows = [g for g in ctx.all(m.Goal) if g.status != "abandoned"]
    return sorted(rows, key=lambda g: (g.status != "active", g.target_date, g.id))


def _owned(ctx: WorkspaceContext, goal_id: str) -> m.Goal:
    goal = next((g for g in ctx.all(m.Goal) if g.id == goal_id), None)
    if goal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such goal in this profile.")
    return goal


def _writable(ctx: WorkspaceContext) -> None:
    if read_only(ctx.workspace):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This profile is read-only.")


def _check_date(on: date) -> None:
    if on <= date.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "A goal's date has to be in the future."
        )


@router.get("", response_model=GoalList)
def list_goals(ctx: Profile) -> GoalList:
    out = GoalList(workspace_id=ctx.workspace_id, goals=[_view(ctx, g) for g in _goals(ctx)])
    ctx.session.commit()  # projections computed for the first time are stored
    return out


@router.post("", response_model=GoalView, status_code=status.HTTP_201_CREATED)
def create_goal(ctx: Profile, body: GoalCreate) -> GoalView:
    _writable(ctx)
    _check_date(body.target_date)
    if sum(g.status == "active" for g in ctx.all(m.Goal)) >= MAX_ACTIVE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"A profile can follow up to {MAX_ACTIVE} goals at once. Archive one first.",
        )
    goal = m.Goal(
        id=new_id("goal"),
        workspace_id=ctx.workspace_id,
        name=body.name,
        currency=ctx.workspace.home_currency,
        target_minor=body.target_minor,
        target_date=body.target_date,
    )
    ctx.add(goal)
    ctx.session.flush()
    ctx.append_audit(
        "goal.created", "goal", goal.id, actor="user",
        after={"name": goal.name, "target_minor": goal.target_minor,
               "target_date": goal.target_date.isoformat()},
    )  # fmt: skip
    view = _view(ctx, goal)
    ctx.session.commit()
    return view


@router.patch("/{goal_id}", response_model=GoalView)
def update_goal(ctx: Profile, goal_id: str, body: GoalUpdate) -> GoalView:
    _writable(ctx)
    goal = _owned(ctx, goal_id)
    sent = body.model_fields_set
    before = {"name": goal.name, "target_minor": goal.target_minor,
              "target_date": goal.target_date.isoformat(), "status": goal.status}  # fmt: skip
    if "target_date" in sent and body.target_date is not None:
        if body.target_date != goal.target_date:
            _check_date(body.target_date)
        goal.target_date = body.target_date
    if "name" in sent and body.name is not None:
        goal.name = body.name
    if "target_minor" in sent and body.target_minor is not None:
        goal.target_minor = body.target_minor
    if "status" in sent and body.status is not None:
        goal.status = body.status
    after = {"name": goal.name, "target_minor": goal.target_minor,
             "target_date": goal.target_date.isoformat(), "status": goal.status}  # fmt: skip
    if after != before:
        action = "goal.archived" if goal.status == "abandoned" else "goal.updated"
        ctx.append_audit(action, "goal", goal.id, actor="user", before=before, after=after)
    view = _view(ctx, goal)
    ctx.session.commit()
    return view
