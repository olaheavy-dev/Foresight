"""Goals API: create, project, edit and archive a save-by-date goal, own profile only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from tests.integration.api.contract import checked
from tests.integration.api.test_engine_api import P1_CSV, demo, new_profile, upload

pytestmark = pytest.mark.postgres
BASE = "https://testserver"


def _goals(client: TestClient) -> Any:
    return checked(client, client.get("/api/goals"), "/api/goals")


def _create(client: TestClient, **body: Any) -> Any:
    response = client.post("/api/goals", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_goal_is_projected_on_the_forecast_and_figures_cite_the_calculation(
    make_client: type[TestClient],
) -> None:
    with (
        make_client(create_app(), base_url=BASE) as alice,
        make_client(create_app(), base_url=BASE) as bob,
    ):
        demo(alice)  # P1 copy: a declared balance and a £500 buffer
        demo(bob)
        on = (date.today() + timedelta(days=120)).isoformat()
        goal = _create(alice, name="  Trip home  ", target_minor=150_000, target_date=on)
        assert goal["name"] == "Trip home"
        block = goal["projection"]
        assert block["type"] == "GoalProjection"
        calc = goal["calc_id"]
        outcome = block["projection"]
        assert outcome["p50"]["ref"] == f"{calc}#progress.p50"  # every figure from the engine
        assert outcome["status_band"] in ("on_track", "at_risk", "off_track")
        assert goal["lower_confidence"] is True  # 120 days out
        # SIM-11 through the API: the shortfall the block implies is target − P50 progress.
        stored = alice.get(f"/api/calculations/{calc}").json()
        assert stored["result"]["shortfall_minor"] == 150_000 - outcome["p50"]["minor"]

        listed = _goals(alice)["goals"]
        assert [g["goal_id"] for g in listed] == [goal["goal_id"]]
        assert listed[0]["calc_id"] == calc  # read back, not recomputed
        assert _goals(bob)["goals"] == []  # never another visitor's
        assert bob.patch(f"/api/goals/{goal['goal_id']}", json={"name": "x"}).status_code == 404

        bigger = alice.patch(f"/api/goals/{goal['goal_id']}", json={"target_minor": 900_000})
        assert bigger.json()["calc_id"] != calc  # a new target is a new projection
        archived = alice.patch(f"/api/goals/{goal['goal_id']}", json={"status": "abandoned"})
        assert archived.json()["projection"] is None
        assert _goals(alice)["goals"] == []


def test_goals_refuse_what_cant_be_projected_honestly(make_client: type[TestClient]) -> None:
    with make_client(create_app(), base_url=BASE) as alice:
        new_profile(alice)
        upload(alice, P1_CSV)  # Monzo CSVs carry no balance: the forecast is relative
        later = (date.today() + timedelta(days=60)).isoformat()
        goal = _create(alice, name="Rainy day", target_minor=50_000, target_date=later)
        assert goal["projection"] is None
        assert "known balance" in goal["problem"]

        past = (date.today() - timedelta(days=1)).isoformat()
        bad = alice.post("/api/goals", json={"name": "x", "target_minor": 1, "target_date": past})
        assert bad.status_code == 422
        zero = alice.post("/api/goals", json={"name": "x", "target_minor": 0, "target_date": later})
        assert zero.status_code == 422
        for i in range(4):
            _create(alice, name=f"g{i}", target_minor=1_000, target_date=later)
        sixth = alice.post(
            "/api/goals", json={"name": "6", "target_minor": 1, "target_date": later}
        )
        assert sixth.status_code == 422  # five active goals at most
        # Reactivating an archived goal counts like creating one (#54 review).
        alice.patch(f"/api/goals/{goal['goal_id']}", json={"status": "abandoned"})
        _create(alice, name="g5", target_minor=1_000, target_date=later)
        back = alice.patch(f"/api/goals/{goal['goal_id']}", json={"status": "active"})
        assert back.status_code == 422


def test_a_goal_waits_for_a_buffer_and_follows_a_new_one(make_client: type[TestClient]) -> None:
    """#54 review: with no buffer, cash above zero isn't all spare; setting one projects it."""
    with make_client(create_app(), base_url=BASE) as alice:
        demo(alice)
        assert alice.patch("/api/session", json={"buffer_minor": None}).status_code == 200
        later = (date.today() + timedelta(days=60)).isoformat()
        goal = _create(alice, name="Rainy day", target_minor=50_000, target_date=later)
        assert goal["projection"] is None
        assert "needs a buffer" in goal["problem"]
        assert alice.patch("/api/session", json={"buffer_minor": 50_000}).status_code == 200
        listed = _goals(alice)["goals"][0]
        assert listed["projection"] is not None  # the buffer is part of the projection's inputs
