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


def test_a_new_prior_gives_a_new_projection(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#54 review: the prior is part of the cache match, so a changed locale pack's prior isn't
    answered with a projection computed on the old one."""
    import dataclasses

    from backend.pipeline import forecast as fc

    with make_client(create_app(), base_url=BASE) as alice:
        demo(alice)
        on = (date.today() + timedelta(days=120)).isoformat()
        first = _create(alice, name="Trip", target_minor=150_000, target_date=on)["calc_id"]
        assert _goals(alice)["goals"][0]["calc_id"] == first  # read back
        old = fc.irregular_prior

        def changed(currency: str) -> Any:
            prior = old(currency)
            return prior and dataclasses.replace(prior, strength_days=prior.strength_days + 7)

        monkeypatch.setattr(fc, "irregular_prior", changed)
        assert _goals(alice)["goals"][0]["calc_id"] != first


def test_a_projection_race_is_retried_not_a_500(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#54 review: two requests projecting the same goal insert the same calculation id; the
    loser rolls back and reads the winner's row instead of failing."""
    from sqlalchemy.exc import IntegrityError

    from backend.app.routers import goals as router

    with make_client(create_app(), base_url=BASE) as alice:
        demo(alice)
        on = (date.today() + timedelta(days=60)).isoformat()
        _create(alice, name="Trip", target_minor=50_000, target_date=on)
        real, calls = router._view, []

        def racing(ctx: Any, goal: Any) -> Any:
            calls.append(goal.id)
            if len(calls) == 1:
                raise IntegrityError("insert calculation", {}, Exception("duplicate key"))
            return real(ctx, goal)

        monkeypatch.setattr(router, "_view", racing)
        listed = alice.get("/api/goals")
        assert listed.status_code == 200, listed.text
        assert len(calls) == 2  # retried once


def test_concurrent_creates_never_pass_the_five_goal_cap(make_client: type[TestClient]) -> None:
    """#54 review: the cap check holds the workspace row until commit, so two creates at four
    active goals can't both succeed."""
    from concurrent.futures import ThreadPoolExecutor

    with make_client(create_app(), base_url=BASE) as alice:
        demo(alice)
        later = (date.today() + timedelta(days=60)).isoformat()
        for i in range(4):
            _create(alice, name=f"g{i}", target_minor=1_000, target_date=later)

        def create(i: int) -> int:
            body = {"name": f"race{i}", "target_minor": 1_000, "target_date": later}
            return alice.post("/api/goals", json=body).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = sorted(pool.map(create, range(2)))
        assert codes == [201, 422]
        active = [g for g in _goals(alice)["goals"] if g["status"] == "active"]
        assert len(active) == 5


def test_a_projection_records_the_forecast_engine_it_ran_on(make_client: type[TestClient]) -> None:
    """#54 review: goals run on the forecast's paths, so the forecast engine version is part of
    the projection's key; a forecast engine upgrade can't read back an old projection."""
    from backend.finance_core.forecast.engine import ENGINE_VERSION

    with make_client(create_app(), base_url=BASE) as alice:
        demo(alice)
        on = (date.today() + timedelta(days=60)).isoformat()
        calc = _create(alice, name="Trip", target_minor=50_000, target_date=on)["calc_id"]
        stored = alice.get(f"/api/calculations/{calc}").json()
        assert stored["params"]["forecast_engine"] == ENGINE_VERSION


def test_goals_due_later_count_what_earlier_ones_leave(make_client: type[TestClient]) -> None:
    """#54 review: two goals can't both claim the same spare cash. The earlier-due goal (on a tie,
    the earlier one made) is funded first; the later one shows what was set aside for it."""
    with make_client(create_app(), base_url=BASE) as alice:
        demo(alice)
        on = (date.today() + timedelta(days=60)).isoformat()
        first = _create(alice, name="Trip", target_minor=40_000, target_date=on)
        second = _create(alice, name="Laptop", target_minor=30_000, target_date=on)
        assert first["reserved"] is None
        assert second["reserved"]["minor"] == 40_000
        assert second["reserved"]["ref"] == f"{second['calc_id']}#goal.reserved_minor"
        # Archiving the earlier goal frees its cash for the later one.
        alice.patch(f"/api/goals/{first['goal_id']}", json={"status": "abandoned"})
        (only,) = _goals(alice)["goals"]
        assert only["reserved"] is None


def test_a_goal_date_is_checked_against_the_profiles_today() -> None:
    """#54 review: "today" is the profile's own, not the server's, so west of UTC near midnight
    tomorrow isn't refused as past."""
    from datetime import datetime
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    from fastapi import HTTPException

    from backend.app.routers.goals import _check_date

    tz = "Etc/GMT+12"  # UTC−12: often a day behind the server
    ctx: Any = SimpleNamespace(workspace=SimpleNamespace(timezone=tz))
    today = datetime.now(ZoneInfo(tz)).date()
    _check_date(ctx, today + timedelta(days=1))  # tomorrow there: accepted
    with pytest.raises(HTTPException):
        _check_date(ctx, today)


def test_a_goal_past_its_date_isnt_shown_as_a_chance(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#54 review: once its date has passed (in the profile's own today), an active goal says so
    and offers a new date or achieved, instead of a projection for a date already gone."""
    from backend.app.routers import goals as router

    with make_client(create_app(), base_url=BASE) as alice:
        demo(alice)
        on = date.today() + timedelta(days=30)
        _create(alice, name="Trip", target_minor=50_000, target_date=on.isoformat())
        monkeypatch.setattr(router, "_today", lambda ctx: on)  # the goal's day has come
        (goal,) = _goals(alice)["goals"]
        assert goal["projection"] is None
        assert "date has passed" in goal["problem"]


def test_rebuilding_the_goal_list_fits_the_calibration_once(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#54 review: after a data change every goal is projected again in one GET; the calibration
    fit doesn't depend on the horizon, so it runs once per request, not once per goal (5 goals
    on 1 CPU: 2.5 s → 0.8 s)."""
    from backend.pipeline import forecast as fc

    with make_client(create_app(), base_url=BASE) as alice:
        demo(alice)
        for i, days in enumerate((60, 90, 120)):
            on = (date.today() + timedelta(days=days)).isoformat()
            _create(alice, name=f"g{i}", target_minor=10_000 + i, target_date=on)
        assert alice.patch("/api/session", json={"buffer_minor": 50_100}).status_code == 200
        real, fits = fc._fit_calibration, []

        def counting(*args: Any, **kwargs: Any) -> Any:
            fits.append(1)
            return real(*args, **kwargs)

        monkeypatch.setattr(fc, "_fit_calibration", counting)
        assert all(g["projection"] for g in _goals(alice)["goals"])
        assert len(fits) == 1
