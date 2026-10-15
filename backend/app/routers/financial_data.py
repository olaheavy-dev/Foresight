"""Financial data for "Check what we found" and the Transactions tabs: accounts with their known
balance, a declared balance, and the income and recurring payments the detectors found.
Engine data only: no agent, no model call."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, status

from backend.app.session import Profile, read_only
from backend.app.ui_contracts.money import money_value
from backend.app.ui_contracts.primitives import DateRange, MoneyAmount
from backend.app.ui_contracts.response import (
    AccountBalance,
    AccountList,
    AccountView,
    BalanceDeclaration,
    DetectedFlows,
    IncomeStreamView,
    RecurringView,
)
from backend.pipeline.ingest import declare_balance
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext

router = APIRouter(prefix="/api", tags=["financial data"])

PROVENANCE = {"declared": "declared"}  # anything else came from a statement's balance column


def _balance(ctx: WorkspaceContext, account: m.Account) -> AccountBalance | None:
    anchors = ctx.anchors(account.id)
    if not anchors:
        return None
    best = max(anchors, key=lambda a: (a.as_of, a.provenance == "declared"))
    return AccountBalance(
        money=money_value(
            MoneyAmount(amount_minor=best.amount_minor, currency=best.currency),
            ctx.workspace.locale,
            "exact",
        ),
        as_of=best.as_of,
        provenance=PROVENANCE.get(best.provenance, "statement_column"),  # type: ignore[arg-type]
    )


def _account_view(ctx: WorkspaceContext, account: m.Account) -> AccountView:
    rows = ctx.transactions(account_ids=[account.id])
    period = (
        DateRange.model_validate({"from": rows[0].posted_on, "to": rows[-1].posted_on})
        if rows
        else None
    )
    return AccountView(
        account_id=account.id,
        name=account.name,
        institution=account.institution,
        type=account.type,
        currency=account.currency,
        tracked=account.tracked,
        transactions=len(rows),
        period=period,
        balance=_balance(ctx, account),
    )


@router.get("/accounts", response_model=AccountList)
def accounts(ctx: Profile) -> AccountList:
    rows = sorted(ctx.all(m.Account), key=lambda a: (a.created_at, a.id))
    return AccountList(
        workspace_id=ctx.workspace_id, accounts=[_account_view(ctx, a) for a in rows]
    )


@router.post("/accounts/{account_id}/balance", response_model=AccountView)
def set_balance(ctx: Profile, account_id: str, body: BalanceDeclaration) -> AccountView:
    """The user's balance on a day (provenance declared): the forecast becomes absolute instead
    of relative. An unchanged answer changes nothing (docs/01 F-10)."""
    if read_only(ctx.workspace):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The demo profile is read-only. Start a new profile to use your own statements.",
        )
    account = next((a for a in ctx.all(m.Account) if a.id == account_id), None)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account in this profile.")
    if body.as_of > date.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "A balance can't be dated in the future."
        )
    declare_balance(ctx, account.id, body.as_of, body.amount_minor)
    ctx.session.commit()
    return _account_view(ctx, account)


@router.get("/detected", response_model=DetectedFlows)
def detected(ctx: Profile) -> DetectedFlows:
    """Income streams and recurring payments as the detectors found them, largest first
    (docs/01 F-17, F-25)."""
    locale = ctx.workspace.locale
    posted: dict[str, date] = {t.id: t.posted_on for t in ctx.transactions()}

    def last(member_ids: list[str]) -> date | None:
        days = [posted[i] for i in member_ids if i in posted]
        return max(days) if days else None

    income = [
        IncomeStreamView(
            income_stream_id=s.id,
            source=s.source_label or "Income",
            amount=money_value(
                MoneyAmount(amount_minor=s.amount_minor, currency=s.currency), locale, "exact"
            ),
            cadence=s.cadence,
            provenance=s.provenance,  # type: ignore[arg-type]
            payments=len(s.member_ids or []),
            last_paid=last(list(s.member_ids or [])),
        )
        for s in ctx.all(m.IncomeStream)
    ]
    recurring = [
        RecurringView(
            recurring_id=o.id,
            label=o.label or o.category_key,
            category_key=o.category_key,
            amount=money_value(
                MoneyAmount(amount_minor=abs(o.amount_minor), currency=o.currency),
                locale,
                "exact",
            ),
            cadence=o.cadence,
            day_of_month=o.anchor_day if o.anchor_day and 1 <= o.anchor_day <= 31 else None,
            is_commitment=o.is_commitment,
            provenance=o.provenance,
            payments=len(o.member_ids or []),
            last_paid=last(list(o.member_ids or [])),
        )
        for o in ctx.all(m.RecurringObligation)
    ]
    income.sort(key=lambda v: -v.amount.minor)
    recurring.sort(key=lambda v: -v.amount.minor)
    return DetectedFlows(workspace_id=ctx.workspace_id, income=income, recurring=recurring)
