"""ING-05 end to end on generated datasets: commit, idempotent re-import, gates."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from backend.pipeline.ingest import correct_category, ingest_file
from backend.storage import models as m
from backend.storage.repositories import CrossWorkspaceError
from tests.integration.pipeline.helpers import (
    DATASETS,
    count,
    dataset,
    export,
    workspace_with_account,
)

pytestmark = pytest.mark.postgres

LEDGER = (m.Transaction, m.SourceRow, m.Categorisation, m.BalanceAnchor)


def test_p1_commits_every_row_once(session: Session) -> None:
    ctx, acct = workspace_with_account(session)
    name, data = export("P1-base")
    truth = dataset("P1-base")["account"]["n_transactions"]

    first = ingest_file(ctx, name, data, account_id=acct)
    assert first.status == "committed"
    assert first.new_rows == truth == count(ctx, m.Transaction)
    assert count(ctx, m.SourceRow) == truth
    # every transaction is categorised exactly once, through the pack and merchant memory
    assert len(ctx.latest_categorisations()) == truth == count(ctx, m.Categorisation)
    # Monzo has no balance column: today's balance is asked, but doesn't block the import
    assert [q.kind for q in first.questions] == ["balance_today"]
    assert count(ctx, m.BalanceAnchor) == 0
    salary = [s for s in ctx.all(m.IncomeStream) if s.cadence == "monthly"]
    assert len(salary) == 1
    assert salary[0].payday_rule is not None
    assert ctx.all(m.RecurringObligation)
    assert ctx.workspace.data_version == 1

    again = ingest_file(ctx, name, data, account_id=acct)
    assert again.status == "already_imported"
    assert again.new_rows == 0

    # An overlapping export (different bytes, same rows) adds nothing either: fingerprints dedupe.
    lines = data.decode().splitlines(keepends=True)
    overlap = "".join(lines[:1] + lines[400:]).encode()
    third = ingest_file(ctx, "monzo-later.csv", overlap, account_id=acct)
    assert third.status == "committed"
    assert third.new_rows == 0
    assert third.tables[0].duplicates == third.tables[0].rows_read > 0
    assert count(ctx, m.Transaction) == truth
    assert ctx.workspace.data_version == 1
    assert ctx.audit_chain_valid()
    session.rollback()


@pytest.mark.parametrize(
    ("name", "kind", "answer"),
    [("G3-dollar", "currency", "USD"), ("G5-ambiguous-date", "date_order", "DMY")],
)
def test_blocking_questions_commit_nothing_until_answered(
    session: Session, name: str, kind: str, answer: str
) -> None:
    ctx, acct = workspace_with_account(session)
    file_name, data = export(name)

    outcome = ingest_file(ctx, file_name, data, account_id=acct)
    assert outcome.status == "needs_review"
    assert kind in {q.kind for q in outcome.questions}
    assert all(count(ctx, model) == 0 for model in LEDGER)
    batches = ctx.all(m.ImportBatch)
    assert [b.status for b in batches] == ["needs_review"]
    assert kind in {q["kind"] for q in batches[0].questions}

    answered = ingest_file(ctx, file_name, data, account_id=acct, answers={kind: answer})
    assert answered.status == "committed"
    assert answered.new_rows == dataset(name)["account"]["n_transactions"]
    # the answered layout is remembered for next time
    assert [p.source for p in ctx.all(m.FormatProfileRow)] == ["user_confirmed"]
    session.rollback()


def test_corrupt_file_is_rejected_with_nothing_committed(session: Session) -> None:
    ctx, acct = workspace_with_account(session)
    path = DATASETS / "CSV-CORRUPT" / "generic_05_dropped_row.csv"

    outcome = ingest_file(ctx, path.name, path.read_bytes(), account_id=acct)
    assert outcome.status == "rejected"
    assert outcome.tables[0].failures
    assert all(count(ctx, model) == 0 for model in LEDGER)
    assert [b.status for b in ctx.all(m.ImportBatch)] == ["rejected"]
    assert [e.action for e in ctx.all(m.AuditEvent)] == ["import.rejected_reconciliation"]
    session.rollback()


def test_unsupported_file_is_explained(session: Session) -> None:
    ctx, acct = workspace_with_account(session)
    outcome = ingest_file(ctx, "statement.pdf", b"%PDF-1.7 ...", account_id=acct)
    assert outcome.status == "unsupported"
    assert outcome.message
    assert count(ctx, m.Transaction) == 0
    session.rollback()


def test_cannot_import_into_another_workspaces_account(session: Session) -> None:
    _, foreign = workspace_with_account(session, "A")
    ctx, _ = workspace_with_account(session, "B")
    name, data = export("P2-base")
    with pytest.raises(CrossWorkspaceError):
        ingest_file(ctx, name, data, account_id=foreign)
    session.rollback()


def test_a_correction_is_appended_and_remembered(session: Session) -> None:
    ctx, acct = workspace_with_account(session)
    name, data = export("P2-base")
    ingest_file(ctx, name, data, account_id=acct)
    txn = next(t for t in ctx.transactions() if t.amount_minor < 0 and t.counterparty)
    before = ctx.latest_categorisations()[txn.id]

    row = correct_category(ctx, txn.id, "gifts")
    assert row.supersedes == before.id
    assert row.method == "user"
    assert ctx.latest_categorisations()[txn.id].category_key == "gifts"
    cpty = ctx.counterparties()[txn.counterparty or ""]
    assert (cpty.default_category_key, cpty.memory_source) == ("gifts", "user")
    session.rollback()
