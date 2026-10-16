"""Settings: a profile's name and buffer, own profile only (PATCH /api/session)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.main import create_app
from backend.settings import get_settings
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext
from tests.integration.api.contract import checked
from tests.integration.api.test_engine_api import demo, new_profile

pytestmark = pytest.mark.postgres
BASE = "https://testserver"


def _patch(client: TestClient, body: dict[str, Any]) -> Any:
    return checked(client, client.patch("/api/session", json=body), "/api/session")


def _prefs_and_job(workspace_id: str) -> tuple[int, str | None]:
    with Session(create_engine(get_settings().database_url)) as db:
        job = db.scalars(
            select(m.AnalysisJob).where(
                m.AnalysisJob.workspace_id == workspace_id, m.AnalysisJob.status == "queued"
            )
        ).first()
        return WorkspaceContext.open(db, workspace_id).prefs_version(), job.event if job else None


def test_settings_rename_and_buffer_leave_the_ledger_version_alone(
    make_client: type[TestClient],
) -> None:
    with (
        make_client(create_app(), base_url=BASE) as alice,
        make_client(create_app(), base_url=BASE) as bob,
    ):
        start = new_profile(alice)
        assert start["buffer_minor"] is None
        bob_before = demo(bob)

        renamed = _patch(alice, {"name": "  Household  "})
        assert renamed["name"] == "Household"
        assert renamed["data_version"] == start["data_version"]  # a name isn't data

        buffered = _patch(alice, {"buffer_minor": 50_000})
        assert buffered["buffer_minor"] == 50_000
        # A preference, not ledger data: the forecast's seed (data_version) stays put, while
        # prefs_version moves so cached answers and advice go stale, and a refresh is queued.
        assert buffered["data_version"] == start["data_version"]
        assert _prefs_and_job(start["workspace_id"]) == (1, "buffer_set")
        _patch(alice, {"buffer_minor": 50_000})
        assert _prefs_and_job(start["workspace_id"])[0] == 1  # unchanged changes nothing

        kept = _patch(alice, {"name": "Home"})  # a field left out stays as it was
        assert kept["buffer_minor"] == 50_000
        cleared = _patch(alice, {"buffer_minor": None})
        assert cleared["buffer_minor"] is None
        assert cleared["data_version"] == start["data_version"]
        assert _prefs_and_job(start["workspace_id"])[0] == 2

        # Refused: a negative buffer, an empty name; another visitor is untouched.
        assert alice.patch("/api/session", json={"buffer_minor": -1}).status_code == 422
        assert alice.patch("/api/session", json={"name": "   "}).status_code == 422
        bob_now = bob.get("/api/session").json()
        assert (bob_now["name"], bob_now["buffer_minor"]) == (
            bob_before["name"],
            bob_before["buffer_minor"],
        )


def test_settings_need_a_profile_and_the_client_header(make_client: type[TestClient]) -> None:
    with make_client(create_app(), base_url=BASE) as alice:
        assert alice.patch("/api/session", json={"name": "X"}).status_code in (401, 404)
        new_profile(alice)
        forged = alice.patch("/api/session", json={"name": "X"}, headers={"X-Foresight-Client": ""})
        assert forged.status_code == 403
