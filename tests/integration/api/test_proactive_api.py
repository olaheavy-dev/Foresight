"""Proactive checked advice after a data change (review R2; backend/app/proactive.py)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from backend.agents import runner
from backend.app import proactive
from backend.settings import get_settings
from backend.storage import models as m
from backend.storage.ids import new_id
from tests.integration.api.contract import checked
from tests.integration.api.test_engine_api import P1_CSV, demo, new_profile, upload

pytestmark = pytest.mark.postgres
U = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def _db() -> Session:
    return Session(create_engine(get_settings().database_url))


def _jobs(workspace_id: str) -> list[m.AnalysisJob]:
    with _db() as db:
        return list(
            db.scalars(select(m.AnalysisJob).where(m.AnalysisJob.workspace_id == workspace_id))
        )


def _due_now(workspace_id: str) -> None:
    with _db() as db:
        db.execute(
            update(m.AnalysisJob)
            .where(m.AnalysisJob.workspace_id == workspace_id)
            .values(not_before=proactive.utcnow() - timedelta(seconds=1))
        )
        db.commit()


def _insights(api: TestClient) -> Any:
    return checked(api, api.get("/api/home/insights"), "/api/home/insights")


def _card(rec_id: str) -> dict[str, Any]:
    pct = {"kind": "percent", "value": 0.4, "display": "40%"}
    return {
        "type": "InterventionCard", "block_id": "b-card",
        "placement": {"area": "tab", "tab": "recommendation"},
        "recommendation_id": rec_id, "version_id": f"{rec_id}-v1", "title": "Move the gym payment",
        "rationale_segments": [{"kind": "text", "text": "It lands before payday."}],
        "actions": [{"type": "timing", "label": "Move it", "detail": ""}],
        "impact": {"p_breach_before": pct, "p_breach_after": pct,
                   "p_breach_window": {"from": "2026-10-01", "to": "2026-10-31"}},
        "verification": {"verdict": "approved", "revisions": 0, "checks_passed": 6,
                         "checks_total": 6, "verification_id": f"ver_{U}"},
        "status": "approved",
    }  # fmt: skip


def test_an_import_queues_one_job_that_a_correction_joins(api: TestClient) -> None:
    profile = new_profile(api)
    upload(api, P1_CSV)
    (job,) = _jobs(profile["workspace_id"])
    assert (job.status, job.event, job.workflow) == ("queued", "import_committed", "ingestion")
    row = api.get("/api/transactions?limit=1").json()["items"][0]
    fixed = api.post(
        f"/api/transactions/{row['transaction_id']}/category", json={"category_key": "groceries"}
    )
    assert fixed.status_code == 200
    (joined,) = _jobs(profile["workspace_id"])  # still one queued job, the import's workflow kept
    assert joined.id == job.id
    assert joined.workflow == "ingestion"
    assert joined.data_version > job.data_version
    assert _insights(api)["status"] == "checking"


def test_without_ai_the_job_is_skipped_and_findings_still_show(api: TestClient) -> None:
    profile = new_profile(api)
    upload(api, P1_CSV)
    _due_now(profile["workspace_id"])
    assert proactive.drain(get_settings().database_url) == 1
    (job,) = _jobs(profile["workspace_id"])
    assert (job.status, job.note) == ("skipped", "ai_paused")  # no Mesh key in tests
    body = _insights(api)
    assert body["status"] == "paused"
    assert body["reason"] == "ai_paused"
    assert body["recommendations"] == []
    assert body["findings"], "P1 has deterministic findings"
    for f in body["findings"]:
        assert "{{" not in f["headline"] + f["detail"]  # every figure filled from its calculation


def test_a_finished_run_shows_its_checked_recommendations(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = new_profile(api)
    # A signed-in person's import runs advice by itself (a guest's waits for the button, #59).
    monkeypatch.setattr(proactive, "advice_on_request_only", lambda ws: False)
    upload(api, P1_CSV)
    _due_now(profile["workspace_id"])
    seen: dict[str, Any] = {}

    def fake_workflow(store: Any, **kwargs: Any) -> runner.RunOutcome:
        seen.update(kwargs)
        run = store.create_run(
            workflow=kwargs["workflow"], trigger="event", data_version=1, prefs_version=0,
            deadline_at=proactive.utcnow() + timedelta(minutes=2), thread_id=None,
        )  # fmt: skip
        rec_id = new_id("rec")
        store.session.add(
            m.Recommendation(
                id=rec_id,
                workspace_id=store.ctx.workspace_id,
                run_id=run.id,
                proposal_key="k",
                status="approved",
                proposal={"card": _card(rec_id)},
            )  # fmt: skip
        )
        store.session.add(
            m.Recommendation(
                id=new_id("rec"),
                workspace_id=store.ctx.workspace_id,
                run_id=run.id,
                proposal_key="k2",
                status="withdrawn",
                proposal={},
            )  # fmt: skip
        )
        store.finish_run(run.id, status="succeeded")
        store.session.commit()
        return runner.RunOutcome(run_id=run.id, status="succeeded", partial=False,
                                 response_id=None, state={})  # fmt: skip

    monkeypatch.setattr(proactive, "advice_blocked", lambda db, ws: None)
    monkeypatch.setattr(runner, "run_workflow", fake_workflow)
    proactive.drain(get_settings().database_url)
    assert (seen["workflow"], seen["event"], seen["trigger"]) == (
        "ingestion",
        "import_committed",
        "event",
    )
    body = _insights(api)
    assert body["status"] == "ready"
    (card,) = body["recommendations"]  # only the approved one
    assert card["title"] == "Move the gym payment"
    assert card["verification"]["verdict"] == "approved"


def test_interrupted_jobs_run_again_after_a_restart(api: TestClient) -> None:
    profile = new_profile(api)
    upload(api, P1_CSV)
    with _db() as db:
        db.execute(
            update(m.AnalysisJob)
            .where(m.AnalysisJob.workspace_id == profile["workspace_id"])
            .values(status="running")
        )
        db.commit()
        assert proactive.recover(db) >= 1
    (job,) = _jobs(profile["workspace_id"])
    assert job.status == "queued"


def test_a_demo_copy_checks_on_request_once_a_day(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo(api)
    body = _insights(api)
    assert body["status"] == "empty"
    assert body["findings"], "the demo shows its findings before any model run"
    # No Mesh key in tests: the button is unavailable and a check is refused, not queued.
    assert body["can_check"] is False
    assert api.post("/api/home/check").status_code == 409

    monkeypatch.setattr(proactive, "advice_blocked", lambda db, ws: None)
    started = api.post("/api/home/check")
    assert started.status_code == 202
    assert started.json()["status"] == "checking"
    monkeypatch.setattr(proactive, "advice_blocked", lambda db, ws: "daily_limit")
    assert api.post("/api/home/check").status_code == 409


def test_a_demo_edit_refreshes_findings_but_never_runs_advice_by_itself(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#43 (Codex): a demo copy spends only from its button, never because of an edit."""
    profile = demo(api)
    row = api.get("/api/transactions?limit=1").json()["items"][0]
    api.post(
        f"/api/transactions/{row['transaction_id']}/category", json={"category_key": "groceries"}
    )
    _due_now(profile["workspace_id"])
    called: list[str] = []

    def record(store: Any, **kwargs: Any) -> None:
        called.append(store.ctx.workspace_id)
        raise RuntimeError("stub: no run")  # other tests' due jobs simply fail here

    monkeypatch.setattr(proactive, "advice_blocked", lambda db, ws: None)  # AI would be available
    monkeypatch.setattr(runner, "run_workflow", record)
    proactive.drain(get_settings().database_url)
    assert profile["workspace_id"] not in called
    (job,) = _jobs(profile["workspace_id"])
    assert (job.status, job.note) == ("skipped", "manual_only")
    body = _insights(api)
    assert body["status"] == "empty"
    assert body["can_check"] is True  # the button is still there


def test_advice_from_an_older_data_version_is_not_shown(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#43 (Codex): after a newer change, the previous run's cards describe a ledger that no
    longer exists; they're withheld whatever the newer job's state."""
    test_a_finished_run_shows_its_checked_recommendations(api, monkeypatch)
    assert _insights(api)["recommendations"]  # shown while they match the data
    row = api.get("/api/transactions?limit=1").json()["items"][0]
    api.post(
        f"/api/transactions/{row['transaction_id']}/category", json={"category_key": "groceries"}
    )
    assert _insights(api)["recommendations"] == []


def test_advice_checked_against_an_older_buffer_is_not_shown(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#53 (Codex): a new buffer leaves the ledger (and the forecast's seed) alone but changes
    what counts as a risk, so the previous run's cards are withheld and a refresh is queued."""
    test_a_finished_run_shows_its_checked_recommendations(api, monkeypatch)
    before = _insights(api)
    assert before["recommendations"]
    api.patch("/api/session", json={"buffer_minor": 123_400})
    after = _insights(api)
    assert after["recommendations"] == []
    assert after["data_version"] == before["data_version"]
    assert after["status"] == "checking"  # the buffer_set refresh is queued


def test_a_guests_own_import_refreshes_findings_but_never_runs_advice_by_itself(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#59 review: a guest can make fresh profiles and import into them; advice there runs only
    from the button, which counts against the network's allowance, so imports can't spend
    uncounted."""
    profile = new_profile(api)
    upload(api, P1_CSV)
    _due_now(profile["workspace_id"])
    called: list[str] = []

    def record(store: Any, **kwargs: Any) -> None:
        called.append(store.ctx.workspace_id)
        raise RuntimeError("stub: no run")

    monkeypatch.setattr(proactive, "advice_blocked", lambda db, ws: None)  # AI would be available
    monkeypatch.setattr(runner, "run_workflow", record)
    proactive.drain(get_settings().database_url)
    assert profile["workspace_id"] not in called
    (job,) = _jobs(profile["workspace_id"])
    assert (job.status, job.note) == ("skipped", "manual_only")
    assert _insights(api)["can_check"] is True
