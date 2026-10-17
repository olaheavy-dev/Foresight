"""Guests' AI work is capped per network per day, so a fresh guest profile doesn't reset it."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import network_cap, proactive
from backend.app.main import create_app
from backend.settings import get_settings
from tests.integration.api.test_engine_api import demo
from tests.integration.api.test_google_auth_api import google, sign_in  # noqa: F401, F811 (fixture)

pytestmark = pytest.mark.postgres
BASE = "https://testserver"
HOME = {"X-Forwarded-For": "81.2.69.160"}
NEIGHBOUR = {"X-Forwarded-For": "81.2.69.44"}  # the same /24
ELSEWHERE = {"X-Forwarded-For": "82.165.10.1"}


@pytest.fixture(autouse=True)
def _fresh_allowance(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    network_cap.allowance.reset()
    monkeypatch.setenv("GUEST_NETWORK_DAILY_CHECKS", "1")  # survives make_client's cache_clear
    get_settings.cache_clear()
    monkeypatch.setattr(proactive, "advice_blocked", lambda db, ws: None)  # AI available
    yield
    network_cap.allowance.reset()


def test_a_new_guest_profile_on_the_same_network_shares_the_days_checks(
    make_client: type[TestClient],
) -> None:
    with (
        make_client(create_app(), base_url=BASE) as first,
        make_client(create_app(), base_url=BASE) as second,
        make_client(create_app(), base_url=BASE) as other,
    ):
        for client in (first, second, other):
            demo(client)
        assert first.post("/api/home/check", headers=HOME).status_code == 202
        refused = second.post("/api/home/check", headers=NEIGHBOUR)  # cookies cleared, same network
        assert refused.status_code == 429
        assert "Sign in with Google" in refused.json()["detail"]
        assert other.post("/api/home/check", headers=ELSEWHERE).status_code == 202


def test_a_guests_question_past_the_networks_allowance_is_refused_with_the_reason(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The question path counts per network too. No model is ever called here: Mesh is
    overridden to unavailable, so the first question degrades and the second is refused."""
    from backend.app.routers import ask as ask_router

    monkeypatch.setenv("GUEST_NETWORK_DAILY_QUESTIONS", "1")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[ask_router.get_mesh] = lambda: None
    with (
        make_client(app, base_url=BASE) as first,
        make_client(app, base_url=BASE) as second,
    ):
        for client in (first, second):
            demo(client)

        def ask(client: TestClient) -> Any:
            thread = client.post("/api/threads").json()["thread_id"]
            return client.post(
                f"/api/threads/{thread}/messages",
                json={"text": "How does next month look?", "client_msg_id": "m1"},
                headers=HOME,
            )

        assert ask(first).status_code == 202
        refused = ask(second)  # a fresh guest profile on the same network
        assert refused.status_code == 429
        assert "guest allowance for your network" in refused.json()["detail"]


def test_a_signed_in_profile_isnt_counted_against_the_guest_allowance(
    google: dict[str, Any],  # noqa: F811 (the imported fixture)
    make_client: type[TestClient],
) -> None:
    """Only guests share a network's allowance: once a guest on that network has used it, a
    signed-in person there still gets their own check."""
    with (
        make_client(create_app(), base_url=BASE) as guest,
        make_client(create_app(), base_url=BASE) as another_guest,
        make_client(create_app(), base_url=BASE) as member,
    ):
        for client in (guest, another_guest, member):
            demo(client)
        assert sign_in(member, google).status_code == 303
        assert guest.post("/api/home/check", headers=HOME).status_code == 202
        assert another_guest.post("/api/home/check", headers=NEIGHBOUR).status_code == 429
        assert member.post("/api/home/check", headers=NEIGHBOUR).status_code == 202


def test_only_an_admitted_question_counts_and_a_refusal_frees_its_slot(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#59 review: a question the profile's own rate limit refuses doesn't use up the network's
    day, and a network refusal doesn't leave the profile's run slot taken."""
    from backend.app.routers import ask as ask_router

    monkeypatch.setenv("GUEST_NETWORK_DAILY_QUESTIONS", "1")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[ask_router.get_mesh] = lambda: None
    real_admit = ask_router.limits.admit
    refusals = iter(["Too many questions in a short time. Please wait a few minutes."])

    def admit_once_refused(workspace_id: str, now: Any) -> str | None:
        return next(refusals, None) or real_admit(workspace_id, now)

    monkeypatch.setattr(ask_router.limits, "admit", admit_once_refused)
    with (
        make_client(app, base_url=BASE) as first,
        make_client(app, base_url=BASE) as second,
    ):
        for client in (first, second):
            demo(client)

        def ask(client: TestClient, msg: str) -> Any:
            thread = client.post("/api/threads").json()["thread_id"]
            return client.post(
                f"/api/threads/{thread}/messages",
                json={"text": "How does next month look?", "client_msg_id": msg},
                headers=HOME,
            )

        assert ask(first, "a").status_code == 429  # the profile's rate limit
        assert ask(first, "b").status_code == 202  # the network's one question is still there
        refused = ask(second, "c")
        assert refused.status_code == 429  # now the network's day is used
        ws = second.get("/api/session").json()["workspace_id"]
        assert ask_router.limits.active[ws] == 0  # its admitted slot was released


def test_a_second_check_while_one_waits_counts_nothing(make_client: type[TestClient]) -> None:
    """#59 review: another tab asking for the same profile's check while one is queued joins it,
    so only one check is counted against the network's day."""
    with (
        make_client(create_app(), base_url=BASE) as tab,
        make_client(create_app(), base_url=BASE) as other_guest,
    ):
        demo(tab)
        demo(other_guest)
        assert tab.post("/api/home/check", headers=HOME).status_code == 202
        assert tab.post("/api/home/check", headers=HOME).status_code == 202  # joins the queued one
        assert sum(network_cap.allowance.counts.values()) == 1


def test_a_slow_start_isnt_given_back_but_a_failed_one_is(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#59 review: a run that only timed out may still start and do the work, so its use isn't
    returned; one that failed to start is."""
    from backend.app.routers import ask as ask_router

    monkeypatch.setenv("GUEST_NETWORK_DAILY_QUESTIONS", "1")
    get_settings.cache_clear()
    monkeypatch.setattr(ask_router, "RUN_START_TIMEOUT_S", 0.05)
    outcome: dict[str, Any] = {"fail": False}

    def background(**kwargs: Any) -> None:  # never starts a run (and never calls a model)
        if outcome["fail"]:
            kwargs["failed"](RuntimeError("could not start"))
        ask_router.limits.release(kwargs["workspace_id"])

    monkeypatch.setattr(ask_router, "_run_in_background", background)
    with make_client(create_app(), base_url=BASE) as guest:
        demo(guest)

        def ask(msg: str) -> int:
            thread = guest.post("/api/threads").json()["thread_id"]
            body = {"text": "How does next month look?", "client_msg_id": msg}
            return int(
                guest.post(f"/api/threads/{thread}/messages", json=body, headers=HOME).status_code
            )

        assert ask("slow") == 503  # timed out: the use stays counted
        assert ask("next") == 429
        network_cap.allowance.reset()
        outcome["fail"] = True
        assert ask("failed") == 503  # failed to start: given back
        outcome["fail"] = False
        assert ask("after") == 503  # the use was there to take (then timed out again)

        # A failure that arrives after the request stopped waiting is given back too, once.
        network_cap.allowance.reset()
        late = threading.Event()

        def fails_late(**kwargs: Any) -> None:
            def later() -> None:
                late.wait(1)
                kwargs["failed"](RuntimeError("could not start"))
                ask_router.limits.release(kwargs["workspace_id"])

            threading.Thread(target=later, daemon=True).start()

        monkeypatch.setattr(ask_router, "_run_in_background", fails_late)
        assert ask("late") == 503
        late.set()
        time.sleep(0.2)
        outcome["fail"] = False
        monkeypatch.setattr(ask_router, "_run_in_background", background)
        assert ask("after-late") == 503  # not 429: the late failure gave the use back


def test_a_check_that_promotes_an_edits_queued_job_counts(make_client: type[TestClient]) -> None:
    """#59 review: an edit queues an automatic job; asking for a check turns it into a manual
    (AI) check, so it counts, otherwise fresh guest profiles could bypass the daily cap."""
    with (
        make_client(create_app(), base_url=BASE) as guest,
        make_client(create_app(), base_url=BASE) as neighbour,
    ):
        demo(guest)
        demo(neighbour)
        assert guest.patch("/api/session", json={"buffer_minor": 60_000}).status_code == 200
        assert guest.post("/api/home/check", headers=HOME).status_code == 202
        assert sum(network_cap.allowance.counts.values()) == 1  # counted
        assert neighbour.post("/api/home/check", headers=NEIGHBOUR).status_code == 429


def test_a_raced_retry_returns_the_existing_run_and_gives_its_count_back(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#59 review: the same question raced in twice makes one run; the second request returns it
    (through `reused`) and its extra count is given back."""
    from backend.app.routers import ask as ask_router

    monkeypatch.setenv("GUEST_NETWORK_DAILY_QUESTIONS", "1")
    get_settings.cache_clear()
    existing = "run_01ARZ3NDEKTSV4RRFFQ69G5FAV"

    def raced(**kwargs: Any) -> None:  # the other request's run already exists
        kwargs["reused"](existing)
        ask_router.limits.release(kwargs["workspace_id"])

    monkeypatch.setattr(ask_router, "_run_in_background", raced)
    with make_client(create_app(), base_url=BASE) as guest:
        demo(guest)
        thread = guest.post("/api/threads").json()["thread_id"]
        body = {"text": "How does next month look?", "client_msg_id": "dup"}
        posted = guest.post(f"/api/threads/{thread}/messages", json=body, headers=HOME)
        assert posted.status_code == 202
        assert posted.json()["run_id"] == existing
        assert sum(network_cap.allowance.counts.values()) == 0  # the duplicate's use came back


def test_a_check_that_fails_to_queue_gives_its_use_back(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#59 review: when queueing the check fails, nothing will run, so the network's use is
    returned."""

    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database unavailable")

    with make_client(create_app(), base_url=BASE) as guest:
        demo(guest)
        monkeypatch.setattr(proactive, "enqueue", broken)
        with pytest.raises(RuntimeError):
            guest.post("/api/home/check", headers=HOME)
        assert sum(network_cap.allowance.counts.values()) == 0


def test_setup_that_fails_before_launch_returns_the_reservation(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#59 review: if launching the run fails, no callback will ever give the use back or free
    the run slot, so the request does it."""
    from backend.app.routers import ask as ask_router

    def broken(**kwargs: Any) -> None:
        raise RuntimeError("thread could not start")

    monkeypatch.setattr(ask_router, "_run_in_background", broken)
    with make_client(create_app(), base_url=BASE) as guest:
        ws = demo(guest)["workspace_id"]
        thread = guest.post("/api/threads").json()["thread_id"]
        body = {"text": "How does next month look?", "client_msg_id": "x"}
        with pytest.raises(RuntimeError):
            guest.post(f"/api/threads/{thread}/messages", json=body, headers=HOME)
        assert sum(network_cap.allowance.counts.values()) == 0
        assert ask_router.limits.active[ws] == 0


def test_a_manual_check_the_worker_just_claimed_counts_as_counted(
    make_client: type[TestClient],
) -> None:
    """#59 review: between the worker claiming a manual check (running) and creating its run,
    another request joins it instead of counting a second time."""
    from sqlalchemy import select, update

    from backend.storage import models as m
    from backend.storage.db import session_factory

    with make_client(create_app(), base_url=BASE) as guest:
        ws = demo(guest)["workspace_id"]
        assert guest.post("/api/home/check", headers=HOME).status_code == 202
        with session_factory(get_settings().database_url)() as db:  # the worker's claim
            db.execute(
                update(m.AnalysisJob)
                .where(m.AnalysisJob.workspace_id == ws)
                .values(status="running")
            )
            db.commit()
        assert guest.post("/api/home/check", headers=HOME).status_code == 202
        assert sum(network_cap.allowance.counts.values()) == 1
        with session_factory(get_settings().database_url)() as db:  # and nothing new is queued
            jobs = db.scalars(select(m.AnalysisJob.status).where(m.AnalysisJob.workspace_id == ws))
            assert sorted(jobs) == ["running"]


def test_a_check_finished_meanwhile_is_rechecked_before_counting(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#59 review: if a manual check finishes between the first look and the lock, the profile's
    day is used; the request is refused without counting a check that would only be skipped."""
    looks = iter([None, "daily_limit"])  # before the lock, then under it
    monkeypatch.setattr(proactive, "advice_blocked", lambda db, ws: next(looks, "daily_limit"))
    with make_client(create_app(), base_url=BASE) as guest:
        demo(guest)
        assert guest.post("/api/home/check", headers=HOME).status_code == 409
        assert sum(network_cap.allowance.counts.values()) == 0
