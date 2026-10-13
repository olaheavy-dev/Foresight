"""The ledger: imported transactions with their current category."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from backend.app.session import Profile
from backend.app.ui_contracts.money import money_value
from backend.app.ui_contracts.primitives import MoneyAmount
from backend.app.ui_contracts.response import TransactionPage, TransactionRow

router = APIRouter(prefix="/api/transactions", tags=["ledger"])


@router.get("", response_model=TransactionPage)
def transactions(
    ctx: Profile,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = Query(default=None, max_length=64),
    flow_kind: str | None = Query(default=None, max_length=32),
    account_id: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TransactionPage:
    total, rows = ctx.transaction_page(
        date_from=date_from,
        date_to=date_to,
        category_key=category,
        flow_kind=flow_kind,
        account_id=account_id,
        limit=limit,
        offset=offset,
    )
    locale = ctx.workspace.locale
    return TransactionPage(
        workspace_id=ctx.workspace_id,
        total=total,
        limit=limit,
        offset=offset,
        items=[
            TransactionRow(
                transaction_id=t.id,
                account_id=t.account_id,
                import_id=t.import_batch_id,
                posted_on=t.posted_on,
                narration=t.description,
                counterparty=t.counterparty,
                channel=t.channel,
                amount=money_value(
                    MoneyAmount(amount_minor=t.amount_minor, currency=t.currency),
                    locale,
                    "exact",
                    ref=t.id,
                ),
                category_key=c.category_key if c else None,
                flow_kind=c.flow_kind if c else None,
                categorised_by=c.method if c else None,  # type: ignore[arg-type]
                confidence=c.confidence if c else None,
            )
            for t, c in rows
        ],
    )
