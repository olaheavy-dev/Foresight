"""Statement import: 1..n CSV files per request, each committed or refused as a whole."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from backend.app.session import Profile, imports_refused
from backend.app.ui_contracts.primitives import DateRange
from backend.app.ui_contracts.response import (
    ImportedFile,
    ImportQuestion,
    ImportReconciliation,
    ImportSummary,
)
from backend.pipeline.ingest import IngestOutcome, ingest_file
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext

router = APIRouter(prefix="/api/imports", tags=["imports"])

MAX_FILES = 10
MAX_BYTES = 10 * 1024 * 1024  # docs/00 §13: CSV ≤ 10 MB

STATUS: dict[str, Literal["imported", "needs_mapping", "rejected"]] = {
    "committed": "imported",
    "already_imported": "imported",
    "needs_review": "needs_mapping",
    "rejected": "rejected",
    "unsupported": "rejected",
}
# finance_core ReconciliationStatus → contract (docs/00 §13: never "reconciled" without balances)
RECONCILIATION: dict[str, tuple[Literal["passed", "failed", "not_possible"], str]] = {
    "reconciled": ("passed", "running_balance"),
    "failed": ("failed", "running_balance"),
    "not_reconcilable_no_balance": ("not_possible", "no_balance_column"),
}


def _source_type(name: str) -> Literal["csv", "xlsx", "xls", "pdf"]:
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return suffix if suffix in ("xlsx", "xls", "pdf") else "csv"  # type: ignore[return-value]


def imported_file(ctx: WorkspaceContext, outcome: IngestOutcome) -> ImportedFile:
    batches = [ctx.get(m.ImportBatch, t.batch_id) for t in outcome.tables if t.batch_id]
    profiles = sorted({b.format_profile_id for b in batches if b and b.format_profile_id})
    currencies = {
        b.format_inference.get("currency") for b in batches if b and b.format_inference
    } - {None}
    firsts: list[date] = []
    lasts: list[date] = []
    for t in outcome.tables:
        if t.status == "committed" and t.batch_id:
            first, last = ctx.batch_date_range(t.batch_id)
            if first and last:
                firsts.append(first)
                lasts.append(last)
    reconciliations = [t.reconciliation for t in outcome.tables if t.reconciliation]
    rec = None
    if reconciliations:
        worst = (
            "failed" if "failed" in reconciliations
            else "not_reconcilable_no_balance" if "not_reconcilable_no_balance" in reconciliations
            else "reconciled"
        )  # fmt: skip
        rec_status, method = RECONCILIATION[worst]
        rec = ImportReconciliation(status=rec_status, method=method)
    rows_read = sum(t.rows_read for t in outcome.tables)
    rows_imported = sum(t.new_rows for t in outcome.tables)
    duplicates = sum(t.duplicates + t.near_duplicates for t in outcome.tables)
    rejected = outcome.status in ("rejected", "unsupported")
    messages = [msg for msg in (outcome.message,) if msg]
    if outcome.status == "already_imported":
        messages.append("This file was imported before, so nothing new was added.")
    return ImportedFile(
        filename=outcome.file_name[:255] or "statement.csv",
        source_type=_source_type(outcome.file_name),
        status=STATUS[outcome.status],
        currency=currencies.pop() if len(currencies) == 1 else None,
        rows_read=rows_read,
        rows_imported=rows_imported,
        rows_rejected=rows_read if rejected else 0,
        reconciliation=rec,
        messages=messages + list(outcome.warnings),
        import_ids=[b.id for b in batches if b],
        already_imported=outcome.status == "already_imported",
        duplicates=duplicates,
        matched_profile=", ".join(profiles) or None,
        period=(
            DateRange.model_validate({"from": min(firsts), "to": max(lasts)}) if firsts else None
        ),
        rejections=[f for t in outcome.tables for f in t.failures],
        questions=[
            ImportQuestion(
                kind=q.kind, prompt=q.prompt, options=list(q.options), preselected=q.preselected
            )
            for q in outcome.questions
        ],  # fmt: skip
    )


ANSWER_KINDS = frozenset({"currency", "date_order", "decimal_separator"})


def _answers(raw: str | None) -> dict[str, str] | None:
    """The user's answers to H13 questions (docs/06 §9), applied to every file in the request."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if (
        not isinstance(parsed, dict)
        or not set(parsed) <= ANSWER_KINDS
        or not all(isinstance(v, str) and 0 < len(v) <= 8 for v in parsed.values())
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"answers must be a JSON object with keys from {sorted(ANSWER_KINDS)}.",
        )
    return parsed


def _ingest_all(
    ctx: WorkspaceContext, payloads: list[tuple[str, bytes]], given: dict[str, str] | None
) -> list[ImportedFile]:
    results = []
    session = ctx.session
    for name, data in payloads:
        # Each file is its own transaction: a refused file never undoes an accepted one.
        try:
            results.append(imported_file(ctx, ingest_file(ctx, name, data, answers=given)))
            session.commit()
        except Exception:
            session.rollback()
            raise
    return results


@router.post("", response_model=ImportSummary)
async def import_statements(
    ctx: Profile,
    files: Annotated[list[UploadFile], File(description="1–10 CSV statement exports")],
    answers: Annotated[
        str | None,
        Form(description='Answers to import questions, as JSON: {"date_order": "DMY"}'),
    ] = None,
) -> ImportSummary:
    if imports_refused(ctx.workspace):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The demo profile holds fictional data. Start a new profile to import your own "
            "statements.",
        )
    if not 1 <= len(files) <= MAX_FILES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Send between 1 and {MAX_FILES} files."
        )
    given = _answers(answers)
    payloads = []
    for upload in files:
        data = await upload.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{upload.filename} is larger than 10 MB."
            )
        payloads.append((upload.filename or "statement.csv", data))

    # Parsing, categorising and forecasting are CPU work: run them on the thread pool, never on
    # the event loop, or every other request to the API waits for this import.
    results = await run_in_threadpool(_ingest_all, ctx, payloads, given)
    first = next((i for f in results for i in f.import_ids), None)
    return ImportSummary(
        import_id=first,
        workspace_id=ctx.workspace_id,
        data_version=ctx.workspace.data_version,
        files=results,
    )
