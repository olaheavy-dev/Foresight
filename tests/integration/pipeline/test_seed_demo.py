"""DEMO-01: demo workspaces are seeded through the real pipeline, and re-seeding changes nothing."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.pipeline.seed_demo import seed_all
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext
from tests.integration.pipeline.helpers import DATASETS, dataset

pytestmark = pytest.mark.postgres

TABLES = (
    m.Workspace, m.Account, m.ImportBatch, m.SourceRow, m.Transaction, m.Categorisation,
    m.BalanceAnchor, m.IncomeStream, m.RecurringObligation, m.Calculation, m.AuditEvent,
)  # fmt: skip


def _counts(session: Session) -> dict[str, int]:
    return {
        t.__tablename__: int(session.scalar(select(func.count()).select_from(t)) or 0)
        for t in TABLES
    }


def test_seed_is_idempotent(session: Session) -> None:
    first = seed_all(session, DATASETS)
    before = _counts(session)
    second = seed_all(session, DATASETS)

    assert [r.persona for r in first] == ["P1", "P2"]
    assert all(r.created and r.new_rows > 0 and r.forecast_created for r in first)
    assert all(not r.created and r.new_rows == 0 and not r.forecast_created for r in second)
    assert [r.workspace_id for r in first] == [r.workspace_id for r in second]
    assert [r.forecast_id for r in first] == [r.forecast_id for r in second]
    assert _counts(session) == before

    p1, p2 = (WorkspaceContext.open(session, r.workspace_id) for r in first)
    p1_spec, p2_spec = dataset("P1-base"), dataset("P2-base")
    assert p1.workspace.kind == "demo"
    assert p1.workspace.persona_key == "P1"
    assert len(p1.transactions()) == p1_spec["account"]["n_transactions"]
    assert len(p2.transactions()) == p2_spec["account"]["n_transactions"]

    declared = p1_spec["workspace"]["declared_balance"]
    [anchor] = p1.all(m.BalanceAnchor)
    assert (anchor.provenance, anchor.source) == ("declared", "demo_seed")
    assert (anchor.as_of, anchor.amount_minor) == (
        date.fromisoformat(declared["as_of"]),
        declared["amount_minor"],
    )
    # P2 has a running balance: its anchor is observed and matches the generator's closing balance
    [p2_anchor] = p2.all(m.BalanceAnchor)
    assert p2_anchor.provenance == "observed"
    assert p2_anchor.amount_minor == p2_spec["workspace"]["closing_balance_minor"]
    assert p1.audit_chain_valid()
    assert p2.audit_chain_valid()
