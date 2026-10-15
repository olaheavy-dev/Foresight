"""Confirming detected income, or saying it isn't income (review R4)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.pipeline.ingest import detect
from backend.settings import get_settings
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext
from tests.integration.api.contract import checked
from tests.integration.api.test_engine_api import P1_CSV, new_profile, upload

pytestmark = pytest.mark.postgres


def _db() -> Session:
    return Session(create_engine(get_settings().database_url))


def _decide(api: TestClient, stream_id: str, decision: str) -> Any:
    response = api.post(f"/api/income/{stream_id}", json={"decision": decision})
    return checked(api, response, "/api/income/{income_stream_id}")


def _forecast_income(workspace_id: str) -> dict[str, str]:
    with _db() as db:
        calc = db.scalars(
            select(m.Calculation)
            .where(m.Calculation.workspace_id == workspace_id, m.Calculation.kind == "forecast")
            .order_by(m.Calculation.created_at.desc())
        ).first()
        assert calc is not None
        return dict(calc.params.get("income_provenance") or {})


def test_confirm_reject_and_undo_income(api: TestClient) -> None:
    profile = new_profile(api)
    upload(api, P1_CSV)
    (salary, *_) = api.get("/api/detected").json()["income"]
    assert salary["provenance"] == "detected"
    version = api.get("/api/session").json()["data_version"]

    confirmed = _decide(api, salary["income_stream_id"], "confirm")
    assert confirmed["provenance"] == "confirmed"
    assert api.get("/api/session").json()["data_version"] == version + 1
    assert _decide(api, salary["income_stream_id"], "confirm")["provenance"] == "confirmed"
    assert api.get("/api/session").json()["data_version"] == version + 1  # no-op: no bump

    api.get("/api/forecast")
    assert "confirmed" in _forecast_income(profile["workspace_id"]).values()
    rejected = _decide(api, salary["income_stream_id"], "reject")
    assert rejected["provenance"] == "rejected"
    api.get("/api/forecast")
    assert "rejected" not in _forecast_income(profile["workspace_id"]).values()
    with _db() as db:
        row = db.get(m.IncomeStream, salary["income_stream_id"])
        assert row is not None
        assert row.key not in _forecast_income(profile["workspace_id"])  # not counted at all

    with _db() as db:  # each real change is audited, by the user
        actions = db.scalars(
            select(m.AuditEvent.action).where(
                m.AuditEvent.workspace_id == profile["workspace_id"],
                m.AuditEvent.action == "income_decision",
            )
        ).all()
        assert len(actions) == 2
        ctx = WorkspaceContext.open(db, profile["workspace_id"])
        detect(ctx)  # re-detection after a later import keeps the user's word
        db.commit()
    again = {s["income_stream_id"]: s for s in api.get("/api/detected").json()["income"]}
    assert again[salary["income_stream_id"]]["provenance"] == "rejected"

    assert _decide(api, salary["income_stream_id"], "undo")["provenance"] == "detected"


def test_income_decisions_are_scoped_and_validated(api: TestClient) -> None:
    new_profile(api)
    upload(api, P1_CSV)
    (salary, *_) = api.get("/api/detected").json()["income"]
    bad = api.post(f"/api/income/{salary['income_stream_id']}", json={"decision": "maybe"})
    assert bad.status_code == 422
    new_profile(api)  # another profile of the same browser cannot reach the first one's income
    other = api.post(f"/api/income/{salary['income_stream_id']}", json={"decision": "confirm"})
    assert other.status_code == 404
