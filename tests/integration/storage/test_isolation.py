"""Workspace isolation: another workspace's rows are invisible and can't be referenced."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.storage import models as m
from backend.storage.ids import new_id
from backend.storage.repositories import (
    CrossWorkspaceError,
    WorkspaceContext,
    WorkspaceNotFound,
    create_workspace,
)

pytestmark = pytest.mark.postgres


def _workspace(session: Session, name: str) -> WorkspaceContext:
    return create_workspace(
        session, name=name, country="GB", home_currency="GBP", locale="en-GB",
        timezone_name="Europe/London",
    )  # fmt: skip


def _ledger(ctx: WorkspaceContext) -> tuple[m.Account, m.Transaction]:
    acct = m.Account(id=new_id("acct"), name="Current", currency="GBP")
    ctx.add(acct)
    ctx.session.flush()
    txn = m.Transaction(
        id=new_id("txn"), account_id=acct.id, posted_on=date(2026, 1, 2), amount_minor=-500,
        currency="GBP", description="SHOP", normalised="SHOP", channel="card", fingerprint="fp:1",
    )  # fmt: skip
    ctx.add(txn)
    ctx.session.flush()
    return acct, txn


def test_reads_never_cross_workspaces(session: Session) -> None:
    a, b = _workspace(session, "A"), _workspace(session, "B")
    acct, txn = _ledger(a)
    a.append_audit("import.committed", "import_batch", "imp_x")

    assert a.get(m.Transaction, txn.id) is not None
    assert b.get(m.Transaction, txn.id) is None
    assert b.get(m.Account, acct.id) is None
    assert b.all(m.Transaction) == []
    assert b.transactions() == []
    assert b.fingerprints(acct.id) == set()
    assert b.latest_categorisations() == {}
    assert b.all(m.AuditEvent) == []
    with pytest.raises(CrossWorkspaceError):
        b.account(acct.id)
    session.rollback()


def test_writes_never_cross_workspaces(session: Session) -> None:
    a, b = _workspace(session, "A"), _workspace(session, "B")
    acct, _ = _ledger(a)

    foreign = m.Account(id=new_id("acct"), workspace_id=a.workspace_id, name="X", currency="GBP")
    with pytest.raises(CrossWorkspaceError):
        b.add(foreign)

    # Even bypassing the context, the composite foreign key refuses a cross-workspace reference.
    session.add(
        m.Transaction(
            id=new_id("txn"), workspace_id=b.workspace_id, account_id=acct.id,
            posted_on=date(2026, 1, 3), amount_minor=-1, currency="GBP", description="X",
            normalised="X", channel="card", fingerprint="fp:x",
        )
    )  # fmt: skip
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_unknown_workspace_is_refused(session: Session) -> None:
    with pytest.raises(WorkspaceNotFound):
        WorkspaceContext.open(session, "wsp_DOESNOTEXIST")
