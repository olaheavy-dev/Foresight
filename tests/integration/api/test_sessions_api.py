"""Sessions, guests and ownership (docs/05 §5.9; review R1, owner decision 15 Oct 2026)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.main import create_app
from backend.app.session import COOKIE, utcnow
from backend.settings import get_settings
from backend.storage import models as m
from tests.integration.api.contract import checked
from tests.integration.api.test_engine_api import demo

pytestmark = pytest.mark.postgres
BASE = "https://testserver"


def _db() -> Session:
    return Session(create_engine(get_settings().database_url))


def test_two_visitors_on_the_same_demo_never_share_conversations(
    make_client: type[TestClient],
) -> None:
    """R1: each visitor gets a private copy of the demo; threads, runs and limits are theirs."""
    with (
        make_client(create_app(), base_url=BASE) as alice,
        make_client(create_app(), base_url=BASE) as bob,
    ):
        a: Any = demo(alice)
        b: Any = demo(bob)
        assert a["persona"] == b["persona"] == "P1"
        assert a["workspace_id"] != b["workspace_id"]
        assert a["read_only"] is True
        assert a["account"] == {"kind": "guest", "name": None, "email": None}
        thread = alice.post("/api/threads").json()["thread_id"]
        assert thread in {t["thread_id"] for t in alice.get("/api/threads").json()["threads"]}
        assert bob.get("/api/threads").json()["threads"] == []
        assert bob.get(f"/api/threads/{thread}").status_code == 404
        posted = bob.post(
            f"/api/threads/{thread}/messages", json={"text": "hi", "client_msg_id": "x"}
        )
        assert posted.status_code == 404
        # Choosing the demo again reuses the same private copy.
        assert demo(alice)["workspace_id"] == a["workspace_id"]
        # Both copies hold the same fictional data and forecast.
        fa = alice.get("/api/forecast").json()["chart"]["summary"]["starting_balance"]
        fb = bob.get("/api/forecast").json()["chart"]["summary"]["starting_balance"]
        assert fa["money"]["minor"] == fb["money"]["minor"]


def test_writes_need_the_client_header(make_client: type[TestClient]) -> None:
    with TestClient(create_app(), base_url=BASE) as bare:
        assert bare.post("/api/session/demo").status_code == 403
    with make_client(create_app(), base_url=BASE) as browser:
        assert browser.post("/api/session/demo").status_code == 200


def test_logout_and_delete_my_data(make_client: type[TestClient]) -> None:
    with make_client(create_app(), base_url=BASE) as guest:
        first = demo(guest)["workspace_id"]
        own = guest.post("/api/session/new").json()["workspace_id"]
        assert guest.get("/api/session").json()["workspace_id"] == own
        assert guest.post("/api/session/delete").status_code == 204
        assert guest.get("/api/session").status_code == 401
        with _db() as db:
            assert db.get(m.Workspace, first) is None
            assert db.get(m.Workspace, own) is None
    with make_client(create_app(), base_url=BASE) as other:
        demo(other)
        assert other.post("/api/session/logout").status_code == 204
        assert other.get("/api/session").status_code == 401
        assert not other.cookies.get(COOKIE)


def test_the_landing_preview_needs_no_session(api: TestClient) -> None:
    preview = checked(api, api.get("/api/public/demo-forecast"), "/api/public/demo-forecast")
    assert preview["chart"]["pay_cycles"]
    assert not api.cookies.get(COOKIE)


def test_expired_guest_data_is_purged_when_the_next_guest_starts(
    make_client: type[TestClient],
) -> None:
    with make_client(create_app(), base_url=BASE) as old:
        ws = demo(old)["workspace_id"]
    with _db() as db:
        owner = db.get(m.Workspace, ws).owner_session_id  # type: ignore[union-attr]
        row = db.get(m.AuthSession, owner)
        assert row is not None
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    with make_client(create_app(), base_url=BASE) as new:
        demo(new)
    with _db() as db:
        assert db.get(m.Workspace, ws) is None
        assert db.scalars(select(m.AuthSession).where(m.AuthSession.id == owner)).first() is None
