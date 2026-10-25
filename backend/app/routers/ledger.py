"""The ledger: imported transactions with their current category."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from backend.app import proactive, views
from backend.app.session import Profile, read_only
from backend.app.ui_contracts.money import money_value
from backend.app.ui_contracts.primitives import MoneyAmount
from backend.app.ui_contracts.response import (
    CategoryCorrected,
    CategoryCorrection,
    CategoryList,
    CategoryOption,
    ImportBatchView,
    ImportHistory,
    TransactionPage,
    TransactionRow,
)
from backend.pipeline import packs
from backend.pipeline.ingest import correct_categories, same_merchant
from backend.storage import models as m

router = APIRouter(prefix="/api/transactions", tags=["ledger"])


@router.get("", response_model=TransactionPage)
def transactions(
    ctx: Profile,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = Query(default=None, max_length=64),
    flow_kind: str | None = Query(default=None, max_length=32),
    account_id: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=80, description="Search narration and payee"),
    review: bool = Query(default=False, description="Only rows to review (docs/01 F-07)"),
    finding: str | None = Query(
        default=None,
        max_length=32,
        description="Only the rows a finding counts (evidence chain): a finding id for its "
        "current rows, or the calc id a stored answer froze them under",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TransactionPage:
    ids = None
    if finding is not None:
        found = views.finding_rows(ctx, finding)
        if found is None:  # another profile's finding is not found, never forbidden
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such finding in this profile.")
        ids = [t.id for t in found]
    total, rows = ctx.transaction_page(
        ids=ids,
        date_from=date_from,
        date_to=date_to,
        category_key=category,
        flow_kind=flow_kind,
        account_id=account_id,
        query=q.strip() if q else None,
        review=review,
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


@router.post("/{transaction_id}/category", response_model=CategoryCorrected)
def correct(ctx: Profile, transaction_id: str, body: CategoryCorrection) -> CategoryCorrected:
    """A user's category correction, appended and taught to merchant memory; with
    `apply_to_merchant`, every other row from the same payee that the user hasn't set by hand
    changes too. The forecast and detection see it at once (data version bump)."""
    if read_only(ctx.workspace):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This profile is read-only.",
        )
    if body.category_key not in packs.categorisation_pack(ctx.workspace.country).categories:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown category.")
    try:
        ids = same_merchant(ctx, transaction_id) if body.apply_to_merchant else [transaction_id]
        correct_categories(ctx, ids, body.category_key)
        proactive.enqueue(ctx, "category_corrected")  # with the correction (R2)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such transaction.") from None
    ctx.session.commit()
    return CategoryCorrected(
        category_key=body.category_key,
        transaction_ids=ids,
        data_version=ctx.workspace.data_version,
    )


categories_router = APIRouter(prefix="/api", tags=["ledger"])


@categories_router.get("/categories", response_model=CategoryList)
def categories(ctx: Profile) -> CategoryList:
    """The profile's categories, for the correction picker (from its locale pack)."""
    pack = packs.categorisation_pack(ctx.workspace.country)
    return CategoryList(
        categories=[
            CategoryOption(key=c.key, nature=c.nature, flow_kind=c.default_flow_kind.value)
            for c in sorted(pack.categories.values(), key=lambda c: c.key)
        ]
    )


@categories_router.get("/imports", response_model=ImportHistory)
def import_history(ctx: Profile) -> ImportHistory:
    """Every import batch, newest first, with its counts and reconciliation (docs/01 F-11)."""
    batches = sorted(ctx.all(m.ImportBatch), key=lambda b: (b.created_at, b.id), reverse=True)
    return ImportHistory(
        workspace_id=ctx.workspace_id,
        imports=[
            ImportBatchView(
                import_id=b.id,
                filename=b.filename or "statement.csv",
                status=b.status,
                account_id=b.account_id,
                format_profile=b.format_profile_id,
                rows_read=int((b.counts or {}).get("rows_read", 0)),
                rows_imported=int((b.counts or {}).get("accepted", 0)),
                duplicates=int((b.counts or {}).get("duplicates", 0))
                + int((b.counts or {}).get("near_duplicates", 0)),
                reconciliation=b.reconciliation_status,
                imported_at=b.created_at,
                message=b.message,
            )
            for b in batches
        ],
    )
