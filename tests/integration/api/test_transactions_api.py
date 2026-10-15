"""Transactions page API: search, the review queue, category correction (one row or every row
from the payee), the category picker and import history (docs/01 F-07, F-11, F-51)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from backend.storage.repositories import WorkspaceContext, demo_workspace
from tests.integration.api.contract import checked
from tests.integration.api.test_engine_api import P1_CSV, demo, new_profile, upload

pytestmark = pytest.mark.postgres

PAGE = "/api/transactions"
FIX = "/api/transactions/{transaction_id}/category"


def test_search_review_categories_and_imports_on_the_demo(api: TestClient) -> None:
    demo(api)
    found: Any = checked(api, api.get(PAGE, params={"q": "deliveroo"}), PAGE)
    assert found["total"] > 0
    for r in found["items"]:
        text = f'{r["narration"]} {r["counterparty"] or ""}'.lower()
        assert "deliveroo" in text
    review: Any = checked(api, api.get(PAGE, params={"review": "true", "limit": 500}), PAGE)
    for r in review["items"]:
        assert r["category_key"] is None or (
            r["categorised_by"] != "user" and r["confidence"] < 0.85
        )
    everything: Any = checked(api, api.get(PAGE), PAGE)
    assert review["total"] < everything["total"]
    cats: Any = checked(api, api.get("/api/categories"), "/api/categories")
    keys = {c["key"] for c in cats["categories"]}
    assert {"food.delivery", "housing.rent", "groceries"} <= keys
    history: Any = checked(api, api.get("/api/imports"), "/api/imports")
    assert history["imports"]
    assert history["imports"][0]["rows_read"] > 0
    row = everything["items"][0]["transaction_id"]
    refused = api.post(FIX.format(transaction_id=row), json={"category_key": "groceries"})
    assert refused.status_code == 403


def test_a_correction_applies_to_the_payee_and_leaves_the_review_queue(api: TestClient) -> None:
    new_profile(api)
    upload(api, P1_CSV)
    page: Any = checked(api, api.get(PAGE, params={"q": "deliveroo", "limit": 500}), PAGE)
    target = page["items"][0]
    sent = api.post(
        FIX.format(transaction_id=target["transaction_id"]),
        json={"category_key": "food.eating_out", "apply_to_merchant": True},
    )
    done: Any = checked(api, sent, FIX)
    same_payee = [r for r in page["items"] if r["counterparty"] == target["counterparty"]]
    assert len(done["transaction_ids"]) >= len(same_payee) > 1
    after: Any = checked(api, api.get(PAGE, params={"q": "deliveroo", "limit": 500}), PAGE)
    changed = [r for r in after["items"] if r["transaction_id"] in set(done["transaction_ids"])]
    assert all(r["category_key"] == "food.eating_out" and r["categorised_by"] == "user"
               for r in changed)  # fmt: skip
    review: Any = checked(api, api.get(PAGE, params={"review": "true", "limit": 500}), PAGE)
    assert not set(done["transaction_ids"]) & {r["transaction_id"] for r in review["items"]}
    bad = api.post(
        FIX.format(transaction_id=target["transaction_id"]), json={"category_key": "nope"}
    )
    assert bad.status_code == 422
    missing = FIX.format(transaction_id="txn_01JAAAAAAAAAAAAAAAAAAAAAAA")
    assert api.post(missing, json={"category_key": "groceries"}).status_code == 404


def test_the_ledger_query_reads_only_this_workspaces_categorisations(seeded: Engine) -> None:
    """#41 (Codex review): with several populated workspaces, both categorisation scans in the
    transaction page are filtered by workspace. Results were identical before; the cost grew with
    every profile on the server, which timed the demo's list out on a busy CI runner."""
    sent: list[str] = []

    def capture(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        sent.append(statement)

    with Session(seeded) as db:
        p1, p2 = demo_workspace(db, "P1"), demo_workspace(db, "P2")
        assert p1 is not None
        assert p2 is not None  # a second populated workspace
        ctx = WorkspaceContext.open(db, p1.id)
        event.listen(seeded, "before_cursor_execute", capture)
        try:
            total, rows = ctx.transaction_page(limit=5)
        finally:
            event.remove(seeded, "before_cursor_execute", capture)
    assert total > 0
    assert all(c is None or c.workspace_id == p1.id for _, c in rows)
    ledger = [s for s in sent if "max(categorisation.seq)" in s]
    assert ledger, "the transaction page query wasn't captured"
    assert all(s.count("categorisation.workspace_id =") >= 2 for s in ledger)
