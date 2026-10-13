"""Import a statement file into a workspace (ING-05, docs/07 §3.2, §4.4).

bytes → `import_file` → gate (blocking questions or a failed reconciliation commit nothing) →
dedupe against stored fingerprints → batch, source rows and transactions → categorise (pack rules
plus merchant memory) → detect income and recurring obligations → balance anchors → audit.

Re-importing the same file, or an overlapping export, adds no transactions. Nothing here commits:
the caller wraps the call in its own database transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from backend.finance_core.categorise.normalise import parse_narration
from backend.finance_core.categorise.pack import CategorisationPack, bank_category_key
from backend.finance_core.categorise.rules import (
    CategoriseContext,
    MemoryEntry,
    categorise,
    learn,
)
from backend.finance_core.detect.income import detect_income_streams
from backend.finance_core.detect.recurring import detect_recurring
from backend.finance_core.importers import (
    FileImport,
    TableImport,
    blocking_questions,
    import_file,
)
from backend.finance_core.importers.anchors import anchor_from_rows
from backend.finance_core.importers.dedupe import dedupe
from backend.finance_core.types import Categorisation, CategorisationMethod, Question
from backend.finance_core.types import ReconciliationStatus as Rec
from backend.finance_core.types import Transaction as Txn
from backend.pipeline import ledger, packs
from backend.storage import models as m
from backend.storage.ids import new_id
from backend.storage.repositories import WorkspaceContext


@dataclass(frozen=True)
class TableOutcome:
    table_index: int
    title: str | None
    batch_id: str | None
    account_id: str | None
    status: str  # committed | already_imported | needs_review | rejected | empty
    rows_read: int = 0
    new_rows: int = 0
    duplicates: int = 0
    near_duplicates: int = 0
    reconciliation: str | None = None
    failures: tuple[str, ...] = ()
    questions: tuple[Question, ...] = ()


@dataclass(frozen=True)
class IngestOutcome:
    file_name: str
    file_sha256: str
    importer: str
    # committed | already_imported | needs_review | rejected | unsupported
    status: str
    message: str | None
    tables: tuple[TableOutcome, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def new_rows(self) -> int:
        return sum(t.new_rows for t in self.tables)

    @property
    def questions(self) -> tuple[Question, ...]:
        return tuple(q for t in self.tables for q in t.questions)


def _question_json(q: Question) -> dict[str, object]:
    return {
        "kind": q.kind,
        "prompt": q.prompt,
        "options": list(q.options),
        "preselected": q.preselected,
    }


def _bank_hint(table: TableImport, pack: CategorisationPack) -> str | None:
    """The bank whose category names the pack has priors for, from the matched profile's label."""
    if table.profile is None:
        return None
    first = table.profile.label.split()[0].lower() if table.profile.label else ""
    key = bank_category_key(first)
    return key if key in pack.bank_category_priors else None


def _batch(
    ctx: WorkspaceContext,
    fi: FileImport,
    index: int,
    table: TableImport,
    status: str,
    account_id: str | None,
) -> m.ImportBatch:
    result = table.result
    batch = m.ImportBatch(
        id=new_id("imp"),
        account_id=account_id,
        importer=fi.importer,
        filename=fi.file_name[:255],
        file_sha256=fi.file_sha256,
        format_profile_id=result.format_profile_id,
        table_index=index,
        table_title=table.title,
        detection={
            "importer": fi.importer,
            "profile_id": result.format_profile_id,
            "profile_origin": table.profile.origin if table.profile else None,
            "tables_found": len(fi.tables),
        },
        format_inference={
            "date_format": result.date_format,
            "currency": result.detected_currency,
            "currency_provenance": result.currency_provenance,
        },
        counts={"rows_read": len(result.rows)},
        status=status,
        reconciliation_status=result.reconciliation.status.value,
        reconciliation_rows_checked=result.reconciliation.rows_checked,
        reconciliation_rows_failed=result.reconciliation.rows_failed,
        reconciliation_failures=list(result.reconciliation.failures),
        questions=[_question_json(q) for q in result.questions],
        warnings=list(result.warnings),
    )
    ctx.add(batch)
    return batch


def _resolve_account(
    ctx: WorkspaceContext,
    fi: FileImport,
    index: int,
    table: TableImport,
    account_id: str | None,
    single_table: bool,
) -> str:
    if account_id is not None and single_table:
        return ctx.account(account_id).id
    ws = ctx.workspace
    currency = table.result.detected_currency or ws.home_currency
    profile = table.result.format_profile_id or fi.importer
    source_key = f"{profile}:{table.title or index}:{currency}"
    existing = ctx.account_by_source_key(source_key)
    if existing is not None:
        return existing.id
    label = table.title or (table.profile.label if table.profile else fi.file_name)
    account = m.Account(
        id=new_id("acct"),
        name=label[:120],
        currency=currency,
        currency_source=table.result.currency_provenance,
        source_key=source_key,
    )
    ctx.add(account)
    ctx.session.flush()
    return account.id


def _save_profile(ctx: WorkspaceContext, table: TableImport, confirmed: bool) -> None:
    profile = table.profile
    if profile is None or profile.origin == "builtin":
        return
    existing = ctx.session.scalars(
        ctx.select(m.FormatProfileRow).where(m.FormatProfileRow.profile_id == profile.profile_id)
    ).first()
    if existing is not None:
        existing.confirmations += 1
        if confirmed:
            existing.source = "user_confirmed"
        return
    ctx.add(
        m.FormatProfileRow(
            id=new_id("fmt"),
            profile_id=profile.profile_id,
            label=profile.label[:120],
            source="user_confirmed" if confirmed else "proposed",
            definition=ledger.profile_json(profile),
            confirmations=1,
        )
    )


def ingest_file(
    ctx: WorkspaceContext,
    file_name: str,
    data: bytes,
    *,
    account_id: str | None = None,
    answers: Mapping[str, str] | None = None,
    actor: str = "user",
) -> IngestOutcome:
    """Import one file. `account_id` names the account for a single-table file; multi-table files
    (e.g. one table per currency pocket) fan out into one account per table."""
    ws = ctx.workspace
    cpack = packs.categorisation_pack(ws.country)
    saved = [ledger.profile(r.definition) for r in ctx.all(m.FormatProfileRow)]
    fi = import_file(
        file_name,
        data,
        pack=packs.locale_pack(ws.country),
        home_currency=ws.home_currency,
        saved_profiles=saved,
        answers=answers,
    )
    if not fi.tables:
        ctx.append_audit(
            "import.rejected", "file", fi.file_sha256, actor=actor, after={"message": fi.message}
        )
        return IngestOutcome(
            fi.file_name, fi.file_sha256, fi.importer, "unsupported", fi.message, (), fi.warnings
        )

    blocked = any(blocking_questions(t.result) for t in fi.tables)
    failed = any(t.result.reconciliation.status == Rec.FAILED for t in fi.tables)
    if blocked or failed:
        # Never a silent partial import: the whole file waits for answers or is rejected.
        status = "rejected" if failed else "needs_review"
        outcomes = []
        for i, table in enumerate(fi.tables):
            batch = _batch(ctx, fi, i, table, status, account_id if len(fi.tables) == 1 else None)
            outcomes.append(
                TableOutcome(
                    table_index=i,
                    title=table.title,
                    batch_id=batch.id,
                    account_id=batch.account_id,
                    status=status,
                    rows_read=len(table.result.rows),
                    reconciliation=table.result.reconciliation.status.value,
                    failures=table.result.reconciliation.failures,
                    questions=table.result.questions,
                )
            )
        action = "import.rejected_reconciliation" if failed else "import.needs_review"
        ctx.append_audit(
            action,
            "import_batch",
            outcomes[0].batch_id or fi.file_sha256,
            actor=actor,
            after={"file_sha256": fi.file_sha256, "tables": len(fi.tables)},
        )
        message = (
            "This file doesn't add up, so nothing was imported."
            if failed
            else "A few questions need an answer before this file can be imported."
        )
        return IngestOutcome(
            fi.file_name, fi.file_sha256, fi.importer, status, message, tuple(outcomes), fi.warnings
        )

    non_empty = [i for i, t in enumerate(fi.tables) if t.result.rows]
    outcomes = []
    new_txns: list[m.Transaction] = []
    banks: dict[str, str | None] = {}
    for i, table in enumerate(fi.tables):
        result = table.result
        if not result.rows:
            outcomes.append(TableOutcome(i, table.title, None, None, "empty"))
            continue
        acct = _resolve_account(ctx, fi, i, table, account_id, len(non_empty) == 1)
        banks[acct] = _bank_hint(table, cpack)
        if ctx.committed_batch(acct, fi.file_sha256, i) is not None:
            outcomes.append(
                TableOutcome(
                    i, table.title, None, acct, "already_imported",
                    rows_read=len(result.rows), duplicates=len(result.rows),
                    reconciliation=result.reconciliation.status.value,
                    questions=result.questions,
                )
            )  # fmt: skip
            continue

        found = dedupe(acct, result.rows, ctx.fingerprints(acct))
        batch = _batch(ctx, fi, i, table, "committed", acct)
        batch.counts = {
            "rows_read": len(result.rows),
            "accepted": len(found.new_rows),
            "duplicates": len(found.duplicates),
            "near_duplicates": len(found.near_duplicates),
        }
        ctx.session.flush()
        new_ids = {id(r) for r in found.new_rows}
        for row in result.rows:
            ctx.add(
                m.SourceRow(
                    id=f"{batch.id}:r{row.source_row_index:06d}",
                    import_batch_id=batch.id,
                    row_number=row.source_row_index,
                    raw=ledger.raw_cells(row),
                    parse_status="ok" if id(row) in new_ids else "duplicate",
                )
            )
        for row, fingerprint in zip(found.new_rows, found.new_fingerprints, strict=True):
            parsed = parse_narration(row.description, row.bank_type, cpack)
            txn = m.Transaction(
                id=new_id("txn"),
                account_id=acct,
                import_batch_id=batch.id,
                source_row_id=f"{batch.id}:r{row.source_row_index:06d}",
                posted_on=row.posted_on,
                posted_time=row.posted_time,
                amount_minor=row.amount_minor,
                currency=row.currency,
                description=row.description,
                normalised=parsed.normalised,
                channel=parsed.channel.value,
                counterparty=parsed.counterparty[:200] if parsed.counterparty else None,
                external_id=row.external_id,
                bank_category=row.bank_category,
                bank_type=row.bank_type,
                balance_after_minor=row.balance_after_minor,
                source_row_index=row.source_row_index,
                fingerprint=fingerprint,
            )
            ctx.add(txn)
            new_txns.append(txn)
        anchor = anchor_from_rows(acct, result.rows)
        if anchor is not None:
            ctx.upsert_anchor(
                acct, anchor.as_of, anchor.amount_minor, anchor.currency,
                source="file_balance_column", provenance="observed", import_batch_id=batch.id,
            )  # fmt: skip
        _save_profile(ctx, table, confirmed=bool(answers))
        outcomes.append(
            TableOutcome(
                table_index=i,
                title=table.title,
                batch_id=batch.id,
                account_id=acct,
                status="committed",
                rows_read=len(result.rows),
                new_rows=len(found.new_rows),
                duplicates=len(found.duplicates),
                near_duplicates=len(found.near_duplicates),
                reconciliation=result.reconciliation.status.value,
                questions=result.questions,  # non-blocking ones, e.g. today's balance
            )
        )
        ctx.append_audit(
            "import.committed", "import_batch", batch.id, actor=actor, after=batch.counts
        )
    ctx.session.flush()

    if new_txns:
        _categorise(ctx, new_txns, banks, cpack)
        ctx.bump_data_version()
        detect(ctx)
    committed = any(o.status == "committed" for o in outcomes)
    return IngestOutcome(
        fi.file_name,
        fi.file_sha256,
        fi.importer,
        "committed" if committed else "already_imported",
        None,
        tuple(outcomes),
        fi.warnings,
    )


# ------------------------------------------------------------------------- categorisation


def merchant_memory(ctx: WorkspaceContext) -> dict[str, MemoryEntry]:
    return {
        c.key: MemoryEntry(c.default_category_key, c.memory_source or "learned")
        for c in ctx.all(m.Counterparty)
        if c.default_category_key
    }


def _counterparty(
    ctx: WorkspaceContext, known: dict[str, m.Counterparty], key: str
) -> m.Counterparty:
    row = known.get(key)
    if row is None:
        row = m.Counterparty(id=new_id("cpty"), key=key, display_name=key.title())
        ctx.add(row)
        known[key] = row
    return row


def _categorise(
    ctx: WorkspaceContext,
    new_txns: Sequence[m.Transaction],
    banks: Mapping[str, str | None],
    cpack: CategorisationPack,
) -> None:
    memory = merchant_memory(ctx)
    known = ctx.counterparties()
    aliases = (ctx.workspace.name.upper(),)
    priors: dict[str, list[Txn]] = {}
    for row in ctx.transactions():
        if row.amount_minor < 0:
            priors.setdefault(row.account_id, []).append(ledger.transaction(row))
    for row in new_txns:
        if row.counterparty:
            row.counterparty_id = _counterparty(ctx, known, row.counterparty).id
        context = CategoriseContext(
            self_aliases=aliases,
            memory=memory,
            bank=banks.get(row.account_id),
            prior_debits=tuple(
                p for p in priors.get(row.account_id, ()) if p.posted_on <= row.posted_on
            ),
        )
        ctx.add(ledger.categorisation_row(categorise(ledger.transaction(row), cpack, context)))
    ctx.session.flush()


def correct_category(
    ctx: WorkspaceContext, transaction_id: str, category_key: str, *, actor: str = "user"
) -> m.Categorisation:
    """A user correction: appended (never overwritten) and taught to merchant memory."""
    txn = ctx.get(m.Transaction, transaction_id)
    if txn is None:
        raise LookupError(transaction_id)
    cpack = packs.categorisation_pack(ctx.workspace.country)
    previous = ctx.latest_categorisations().get(transaction_id)
    row = ledger.categorisation_row(
        Categorisation(
            transaction_id,
            category_key,
            cpack.default_flow_kind(category_key),
            CategorisationMethod.USER,
            1.0,
            "your correction",
        ),
        supersedes=previous.id if previous else None,
    )
    ctx.add(row)
    if txn.counterparty:
        memory = learn(merchant_memory(ctx), txn.counterparty, category_key, "user")
        cpty = _counterparty(ctx, ctx.counterparties(), txn.counterparty)
        cpty.default_category_key = memory[txn.counterparty].category_key
        cpty.memory_source = memory[txn.counterparty].source
    ctx.append_audit(
        "txn.recategorised", "transaction", transaction_id, actor=actor,
        before={"category_key": previous.category_key} if previous else None,
        after={"category_key": category_key},
    )  # fmt: skip
    ctx.bump_data_version()
    detect(ctx)
    return row


# ------------------------------------------------------------------------- detection


def detect(ctx: WorkspaceContext) -> tuple[int, int]:
    """Re-run income and recurring detection over the workspace's home-currency ledger and replace
    the detected rows. Returns (income streams, obligations)."""
    ws = ctx.workspace
    cpack = packs.categorisation_pack(ws.country)
    rows = ctx.transactions(currency=ws.home_currency)
    if not rows:
        return (0, 0)
    txns = [ledger.transaction(r) for r in rows]
    latest = ctx.latest_categorisations()
    cats = [ledger.categorisation(latest[r.id]) for r in rows if r.id in latest]
    holidays = packs.holidays(ws.country, (rows[0].posted_on, rows[-1].posted_on))
    streams = detect_income_streams(
        txns, cats, holidays, shift_rule=cpack.payday_shift, one_off_multiple=cpack.one_off_multiple
    )
    report = detect_recurring(txns, cats, cpack, holidays)
    ctx.replace_detected(m.IncomeStream, [ledger.income_row(s) for s in streams])
    ctx.replace_detected(
        m.RecurringObligation, [ledger.obligation_row(o) for o in report.obligations]
    )
    ctx.session.flush()
    return (len(streams), len(report.obligations))


# ------------------------------------------------------------------------- balances


def declare_balance(
    ctx: WorkspaceContext,
    account_id: str,
    on: date,
    amount_minor: int,
    *,
    source: str = "user_entered",
    actor: str = "user",
) -> m.BalanceAnchor:
    """The user's "balance today" (provenance declared). Unchanged answers change nothing."""
    acct = ctx.account(account_id)
    before = next(
        (a for a in ctx.anchors(account_id) if a.as_of == on and a.source == source), None
    )
    if before is not None and before.amount_minor == amount_minor:
        return before
    anchor = ctx.upsert_anchor(
        account_id, on, amount_minor, acct.currency, source=source, provenance="declared"
    )
    ctx.session.flush()
    ctx.append_audit(
        "balance.declared", "balance_anchor", anchor.id, actor=actor,
        after={"account_id": account_id, "as_of": on.isoformat(), "amount_minor": amount_minor},
    )  # fmt: skip
    ctx.bump_data_version()
    return anchor
