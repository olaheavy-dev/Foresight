"""Activity: agent runs as traces and the audit log in words, own profile only."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.main import create_app
from backend.app.session import utcnow
from backend.settings import get_settings
from backend.storage import models as m
from backend.storage.ids import new_id
from tests.integration.api.contract import checked
from tests.integration.api.test_engine_api import demo

pytestmark = pytest.mark.postgres
BASE = "https://testserver"


def _activity(client: TestClient) -> Any:
    return checked(client, client.get("/api/activity"), "/api/activity")


def _seed_run(workspace_id: str) -> str:
    """A finished run with a model step, a tool step and a Verifier approval."""
    now = utcnow()
    step = {"workspace_id": workspace_id, "started_at": now, "finished_at": now, "status": "ok"}
    with Session(create_engine(get_settings().database_url)) as db:
        run_id = new_id("run")
        db.add(
            m.AgentRun(
                id=run_id, workspace_id=workspace_id, workflow="conversation", trigger="user",
                status="succeeded", data_version=1, deadline_at=now + timedelta(minutes=1),
                started_at=now, finished_at=now + timedelta(seconds=12), llm_calls=1,
                tokens_in=900, tokens_out=200, cost_estimate_usd=0.012, revision_count=1,
            )
        )  # fmt: skip
        db.flush()
        db.add(
            m.AgentStep(
                id=new_id("step"), run_id=run_id, seq=1, node="advise", agent="advisor",
                kind="llm", provider="mesh", model="anthropic/claude-sonnet-5.5",
                tier="reasoning", label="Drafting advice", latency_ms=8000, tokens_in=900,
                tokens_out=200, cost_estimate_usd=0.012, input_hash="h1",
                output={"secret": "model output must not leak"}, **step,
            )
        )  # fmt: skip
        db.add(
            m.AgentStep(
                id=new_id("step"), run_id=run_id, seq=2, node="verify", agent="verifier",
                kind="tool", label="Checking the draft", latency_ms=40, input_hash="h2", output={},
                **step,
            )
        )  # fmt: skip
        thread = new_id("thr")
        db.add(m.Thread(id=thread, workspace_id=workspace_id))
        db.flush()
        db.add(
            m.Message(
                id=new_id("msg"), workspace_id=workspace_id, thread_id=thread, seq=1,
                role="user", text="What about £800?", run_id=run_id,
                standalone_question="Can I afford a £800 purchase on 20 November?",
            )
        )  # fmt: skip
        db.flush()
        rec = new_id("rec")
        db.add(
            m.Recommendation(
                id=rec, workspace_id=workspace_id, run_id=run_id, proposal_key="k",
                status="approved", proposal={},
            )
        )  # fmt: skip
        db.flush()
        db.add(
            m.VerificationResult(
                id=new_id("ver"), workspace_id=workspace_id, run_id=run_id,
                recommendation_id=rec, round=1, verdict="APPROVE", rule_results=[],
            )
        )  # fmt: skip
        db.commit()
        return run_id


def test_runs_are_traces_and_the_audit_log_reads_in_words(
    make_client: type[TestClient],
) -> None:
    with (
        make_client(create_app(), base_url=BASE) as alice,
        make_client(create_app(), base_url=BASE) as bob,
    ):
        mine = demo(alice)["workspace_id"]
        demo(bob)
        start = _activity(alice)
        assert start["audit_chain_intact"] is True
        assert start["audit_events"] > 0
        assert any(
            e["summary"].startswith("Imported ") and "table" in e["summary"]
            for e in start["events"]
        )

        # One payee-wide correction is one line, not one per transaction.
        row = alice.get("/api/transactions?q=deliveroo&limit=1").json()["items"][0]
        alice.post(
            f"/api/transactions/{row['transaction_id']}/category",
            json={"category_key": "food.eating_out", "apply_to_merchant": True},
        )
        events = _activity(alice)["events"]
        changed = [e for e in events if e["action"] == "txn.recategorised"]
        assert len(changed) == 1
        assert changed[0]["summary"].startswith("Changed the category of ")

        # Two separate single-row corrections stay two lines, never one "bulk" change (#50 review).
        rows = alice.get("/api/transactions?q=tesco&limit=2").json()["items"]
        for r in rows:
            alice.post(
                f"/api/transactions/{r['transaction_id']}/category",
                json={"category_key": "food.eating_out", "apply_to_merchant": False},
            )
        changed = [e for e in _activity(alice)["events"] if e["action"] == "txn.recategorised"]
        assert [e["summary"] for e in changed[:2]] == ["Changed a transaction’s category"] * 2

        # Settings changes read in words too.
        alice.patch("/api/session", json={"buffer_minor": 40_000})
        assert _activity(alice)["events"][0]["summary"] == "Changed the buffer"

        run_id = _seed_run(mine)
        body = _activity(alice)
        (run,) = [r for r in body["runs"] if r["run_id"] == run_id]
        assert (run["duration_ms"], run["approved"], run["rejected"]) == (12000, 1, 0)
        # The person's words, never the model's rewrite, which could carry a figure (#50 review).
        assert run["question"] == "What about £800?"
        assert [s["agent"] for s in run["steps"]] == ["advisor", "verifier"]
        assert run["steps"][0]["model"] == "anthropic/claude-sonnet-5.5"
        assert "model output must not leak" not in alice.get("/api/activity").text

        assert all(r["run_id"] != run_id for r in _activity(bob)["runs"])  # never another's
        assert all(e["action"] != "txn.recategorised" for e in _activity(bob)["events"])
