"""Guests' AI work is capped per network per day, so a fresh guest profile doesn't reset it."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app import network_cap, proactive
from backend.app.main import create_app
from backend.settings import get_settings
from tests.integration.api.test_engine_api import demo

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
