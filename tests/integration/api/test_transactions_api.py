"""Transactions page API: search, the review queue, category correction (one row or every row
from the payee), the category picker and import history (docs/01 F-07, F-11, F-51)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from backend.storage.repositories import WorkspaceContext
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


def test_a_fresh_import_pages_fast_even_when_planner_statistics_predate_it(
    api: TestClient, seeded: Engine
) -> None:
    """#41 (Codex review, then CI): statistics gathered while a new profile was still empty made
    the planner expect one row, and a grouped "latest categorisation" subquery got a nested-loop
    plan that ran for minutes on a 1,126-row import. Recreate exactly that, then require every
    page variant within a statement timeout. Each row's categorisation must be its own
    workspace's."""
    profile = new_profile(api)
    with Session(seeded) as db:  # statistics now say this workspace has no rows at all
        db.execute(text("ANALYZE transaction"))
        db.execute(text("ANALYZE categorisation"))
        db.commit()
    upload(api, P1_CSV)
    with Session(seeded) as db:
        db.execute(text("SET statement_timeout = '3s'"))
        ctx = WorkspaceContext.open(db, profile["workspace_id"])
        for kwargs in ({}, {"review": True, "limit": 1}, {"query": "deliveroo"}):
            total, rows = ctx.transaction_page(**kwargs)  # type: ignore[arg-type]
            assert total > 0
            assert all(c is None or c.workspace_id == profile["workspace_id"] for _, c in rows)
