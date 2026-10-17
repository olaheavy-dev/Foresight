"""Guests' AI work is capped per network per day, so a fresh guest profile doesn't reset it."""

from __future__ import annotations

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
