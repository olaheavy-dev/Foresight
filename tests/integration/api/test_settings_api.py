"""Settings: a profile's name and buffer, own profile only (PATCH /api/session)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from tests.integration.api.contract import checked
from tests.integration.api.test_engine_api import demo, new_profile

pytestmark = pytest.mark.postgres
BASE = "https://testserver"


def _patch(client: TestClient, body: dict[str, Any]) -> Any:
    return checked(client, client.patch("/api/session", json=body), "/api/session")


def test_settings_rename_and_buffer_bump_the_data_version_once(
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
        assert buffered["data_version"] == start["data_version"] + 1  # the forecast depends on it
        again = _patch(alice, {"buffer_minor": 50_000})
        assert again["data_version"] == buffered["data_version"]  # unchanged changes nothing

        kept = _patch(alice, {"name": "Home"})  # a field left out stays as it was
        assert kept["buffer_minor"] == 50_000
        cleared = _patch(alice, {"buffer_minor": None})
        assert cleared["buffer_minor"] is None
        assert cleared["data_version"] == buffered["data_version"] + 1

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
