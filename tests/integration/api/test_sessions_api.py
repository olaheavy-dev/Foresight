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
        copy = demo(other)["workspace_id"]
        assert other.post("/api/session/logout").status_code == 204
        assert other.get("/api/session").status_code == 401
        assert not other.cookies.get(COOKIE)
        with _db() as db:  # Codex review on #38: a guest's data goes at sign-out, not later
            assert db.get(m.Workspace, copy) is None


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


def _drain_worker() -> None:
    """The pool's single worker runs jobs in order: a no-op finishing means every seed has."""
    from backend.app import demo_pool

    demo_pool._pool().submit(int).result(timeout=120)


def test_demo_copies_come_from_a_warm_pool_seeded_in_a_worker_process(
    make_client: type[TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seeding is CPU work, so it runs in a separate process ahead of time; a visitor claims a
    ready copy. Unclaimed copies have no owner, so no browser can open them, and the orphan
    purge leaves them alone."""
    from backend.app import demo_pool
    from backend.app.routers.session import purge_expired

    monkeypatch.setenv("DEMO_POOL_SIZE", "1")
    monkeypatch.setattr(demo_pool, "REFILL_DELAY_SECONDS", 0.0)
    get_settings.cache_clear()
    with make_client(create_app(), base_url=BASE) as first:  # start-up queues one seed
        _drain_worker()
        with _db() as db:
            pooled = db.scalars(demo_pool._unowned("P1")).all()
        assert len(pooled) == 1
        claimed = demo(first)["workspace_id"]
        assert claimed == pooled[0].id  # the ready copy, not a fresh seed
        demo_pool._refills["P1"].join(timeout=30)  # the claim scheduled a refill
        _drain_worker()
        with _db() as db:
            spare = db.scalars(demo_pool._unowned("P1")).one()
            assert spare.id != claimed
            spare.created_at = utcnow() - timedelta(days=30)
            db.commit()
            purge_expired(db)
            db.commit()
            assert db.get(m.Workspace, spare.id) is not None


def _legacy_cookie(workspace_id: str) -> str:
    """A `foresight_profile` cookie exactly as the pre-accounts API signed it."""
    import base64
    import hashlib
    import hmac

    mac = hmac.new(b"test-only-secret", workspace_id.encode(), hashlib.sha256).digest()
    return f"{workspace_id}.{base64.urlsafe_b64encode(mac).decode().rstrip('=')}"


def test_profiles_from_before_accounts_survive_the_purge_and_their_browser_adopts_them(
    make_client: type[TestClient],
) -> None:
    """Codex review on #36: after migration 0007 old profiles have no owner. They must not be
    purged, and the browser holding the old signed cookie keeps its profile."""
    from backend.app.routers.session import purge_expired
    from backend.storage.repositories import create_workspace

    with _db() as db:
        legacy = create_workspace(
            db,
            name="Imported before accounts",
            country="GB",
            home_currency="GBP",
            locale="en-GB",
            timezone_name="Europe/London",
            kind="user",
        ).workspace_id
        ws = db.get(m.Workspace, legacy)
        assert ws is not None
        ws.created_at = utcnow() - timedelta(days=30)
        db.commit()

    with make_client(create_app(), base_url=BASE) as stranger:
        demo(stranger)  # a new guest arriving runs the purge
    with _db() as db:
        purge_expired(db)
        db.commit()
        assert db.get(m.Workspace, legacy) is not None

    with make_client(create_app(), base_url=BASE) as forged:
        bad = f"foresight_profile={legacy}.not-the-signature"
        assert forged.get("/api/session", headers={"cookie": bad}).status_code == 401

    with make_client(create_app(), base_url=BASE) as returning:
        old = f"foresight_profile={_legacy_cookie(legacy)}"
        first = returning.get("/api/session", headers={"cookie": old})
        assert first.status_code == 200, first.text
        assert first.json()["workspace_id"] == legacy
        assert returning.cookies.get(COOKIE)  # now a normal guest session
        assert returning.get("/api/session").json()["workspace_id"] == legacy
    with _db() as db:
        ws = db.get(m.Workspace, legacy)
        assert ws is not None
        assert ws.owner_session_id is not None
