"""The audit log as the Activity feed reads it: the incremental chain check (#51) and groups that
run past the feed's read window (#52)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.routers.activity import _events
from backend.storage import repositories
from backend.storage.repositories import WorkspaceContext, create_workspace

pytestmark = pytest.mark.postgres


def _workspace(session: Session) -> WorkspaceContext:
    return create_workspace(
        session, name="Test", country="GB", home_currency="GBP", locale="en-GB",
        timezone_name="Europe/London",
    )  # fmt: skip


def _tamper(session: Session, seq: int, ctx: WorkspaceContext) -> None:
    # Only an explicit purge may delete; a deleted row is the tampering a chain must show.
    session.execute(text("SET LOCAL foresight.purge = 'on'"))
    session.execute(
        text("DELETE FROM audit_event WHERE workspace_id = :w AND seq = :s"),
        {"w": ctx.workspace_id, "s": seq},
    )
    session.expire_all()


def test_the_incremental_check_rehashes_only_new_rows(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _workspace(session)
    for i in range(5):
        ctx.append_audit("balance.declared", "account", f"acct_{i}")
    assert ctx.audit_chain_valid(incremental=True)
    assert repositories._AUDIT_CHECKPOINTS[ctx.workspace_id][0] == 5

    hashed: list[str] = []
    real = repositories.audit_hash
    monkeypatch.setattr(
        repositories, "audit_hash", lambda prev, body: hashed.append(prev) or real(prev, body)
    )
    ctx.append_audit("balance.declared", "account", "acct_5")
    hashed.clear()  # the append hashes its own row
    assert ctx.audit_chain_valid(incremental=True)
    assert len(hashed) == 1  # only the row appended since the last read
    hashed.clear()
    assert ctx.audit_chain_valid()  # a full check still re-hashes everything
    assert len(hashed) == 6
    session.rollback()


def test_the_incremental_check_still_fails_a_broken_chain(session: Session) -> None:
    ctx = _workspace(session)
    for i in range(4):
        ctx.append_audit("balance.declared", "account", f"acct_{i}")
    assert ctx.audit_chain_valid(incremental=True)  # checkpoint at seq 4
    ctx.append_audit("balance.declared", "account", "acct_4")
    ctx.append_audit("balance.declared", "account", "acct_5")
    _tamper(session, 5, ctx)  # a row after the checkpoint
    assert not ctx.audit_chain_valid(incremental=True)
    assert ctx.workspace_id not in repositories._AUDIT_CHECKPOINTS
    session.rollback()


def test_a_missing_checkpoint_row_fails_the_incremental_check(session: Session) -> None:
    ctx = _workspace(session)
    for i in range(3):
        ctx.append_audit("balance.declared", "account", f"acct_{i}")
    assert ctx.audit_chain_valid(incremental=True)  # checkpoint at seq 3
    _tamper(session, 3, ctx)
    assert not ctx.audit_chain_valid(incremental=True)
    session.rollback()


def test_a_correction_longer_than_the_read_window_shows_its_whole_count(session: Session) -> None:
    ctx = _workspace(session)
    ctx.append_audit("balance.declared", "account", "acct_0")
    limit = 2  # a window of 40 rows
    for i in range(45):  # one correction applied to 45 payments, straddling the window
        ctx.append_audit(
            "txn.recategorised", "transaction", f"txn_{i}", actor="user", after={"batch": "b1"}
        )
    ctx.append_audit("import.committed", "import", "imp_0")
    events = _events(ctx, limit)
    assert [e.action for e in events] == ["import.committed", "txn.recategorised"]
    assert events[1].summary == "Changed the category of 45 transactions"
    session.rollback()
