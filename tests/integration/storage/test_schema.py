"""Migration round trip, id prefixes, append-only tables and the audit hash chain."""

from __future__ import annotations

from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from backend.storage import models as m
from backend.storage.ids import new_id
from backend.storage.repositories import WorkspaceContext, create_workspace
from tests.integration.storage.disposable import alembic_config, disposable_database

pytestmark = pytest.mark.postgres

TABLES = {
    "workspace", "account", "format_profile", "import_batch", "source_row", "counterparty",
    "transaction", "categorisation", "balance_anchor", "income_stream", "recurring_obligation",
    "calculation", "audit_event",
}  # fmt: skip


def _workspace(session: Session) -> WorkspaceContext:
    return create_workspace(
        session, name="Test", country="GB", home_currency="GBP", locale="en-GB",
        timezone_name="Europe/London",
    )  # fmt: skip


def _account(ctx: WorkspaceContext) -> m.Account:
    acct = m.Account(id=new_id("acct"), name="Current", currency="GBP")
    ctx.add(acct)
    ctx.session.flush()
    return acct


def _txn(ctx: WorkspaceContext, account_id: str, n: int = 0) -> m.Transaction:
    txn = m.Transaction(
        id=new_id("txn"), account_id=account_id, posted_on=date(2026, 1, 2), amount_minor=-1234,
        currency="GBP", description="SHOP", normalised="SHOP", channel="card",
        fingerprint=f"fp:{n}",
    )  # fmt: skip
    ctx.add(txn)
    ctx.session.flush()
    return txn


def test_round_trip_in_a_disposable_database() -> None:
    with disposable_database() as url:
        config = alembic_config(url)
        engine = create_engine(url)
        command.upgrade(config, "head")
        assert TABLES <= set(inspect(engine).get_table_names())
        command.downgrade(config, "base")
        assert not TABLES & set(inspect(engine).get_table_names())
        command.upgrade(config, "head")
        assert TABLES <= set(inspect(engine).get_table_names())
        engine.dispose()


def test_ids_must_carry_their_prefix(session: Session) -> None:
    ctx = _workspace(session)
    ctx.add(m.Account(id="x_01TEST", name="Current", currency="GBP"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_fingerprint_is_unique_per_account(session: Session) -> None:
    ctx = _workspace(session)
    acct = _account(ctx)
    _txn(ctx, acct.id, 1)
    with pytest.raises(IntegrityError):
        _txn(ctx, acct.id, 1)
    session.rollback()


def test_categorisations_are_append_only(session: Session) -> None:
    ctx = _workspace(session)
    txn = _txn(ctx, _account(ctx).id)
    ctx.add(
        m.Categorisation(
            id=new_id("ctg"), transaction_id=txn.id, category_key="groceries",
            flow_kind="spending", method="rule", confidence=0.9,
        )
    )  # fmt: skip
    session.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("UPDATE categorisation SET category_key = 'other'"))
    session.rollback()


def test_audit_chain_links_and_detects_a_removed_event(session: Session) -> None:
    ctx = _workspace(session)
    events = [ctx.append_audit("balance.declared", "account", f"acct_{i}") for i in range(3)]
    assert [e.seq for e in events] == [1, 2, 3]
    assert events[1].prev_hash == events[0].hash
    assert events[2].prev_hash == events[1].hash
    assert ctx.audit_chain_valid()

    with pytest.raises(DBAPIError, match="append-only"), session.begin_nested():
        session.execute(text("UPDATE audit_event SET actor = 'user'"))
    with pytest.raises(DBAPIError, match="append-only"), session.begin_nested():
        session.execute(text("DELETE FROM audit_event"))

    # Only an explicit purge may delete, and the chain then shows the gap.
    session.execute(text("SET LOCAL foresight.purge = 'on'"))
    session.execute(text("DELETE FROM audit_event WHERE id = :id"), {"id": events[1].id})
    session.expire_all()
    assert not ctx.audit_chain_valid()
    session.rollback()
