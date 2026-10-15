"""Google sign-in (OIDC + PKCE) with Google replaced: a test RSA key signs the ID token and the
token exchange is scripted (owner decision 15 Oct 2026)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.routers import auth
from backend.app.session import COOKIE
from backend.settings import get_settings
from tests.integration.api.test_engine_api import demo

pytestmark = pytest.mark.postgres
BASE = "https://testserver"
CLIENT_ID = "test-client.apps.googleusercontent.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def google(
    monkeypatch: pytest.MonkeyPatch, make_client: type[TestClient]
) -> Iterator[dict[str, Any]]:
    """Configure Google sign-in and script the provider. `claims` shapes the next ID token."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE)
    get_settings.cache_clear()
    state: dict[str, Any] = {"claims": {}, "nonce": None}

    def exchange(code: str, verifier: str) -> dict[str, Any]:
        assert code == "the-code"
        assert verifier
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "sub": "google-123",
            "email": "amara@example.com",
            "email_verified": True,
            "name": "Amara Test",
            "iat": now,
            "exp": now + 600,
            "nonce": state["nonce"],
            **state["claims"],
        }
        return {"id_token": jwt.encode(claims, KEY, algorithm="RS256")}

    monkeypatch.setattr(auth, "exchange_code", exchange)
    monkeypatch.setattr(auth, "signing_key", lambda _token: KEY.public_key())
    yield state
    get_settings.cache_clear()


def sign_in(client: TestClient, state: dict[str, Any], *, next_path: str = "/home") -> Any:
    start = client.get("/api/auth/google/start", params={"next": next_path}, follow_redirects=False)
    assert start.status_code == 303
    query = parse_qs(urlparse(start.headers["location"]).query)
    state["nonce"] = query["nonce"][0]
    return client.get(
        "/api/auth/google/callback",
        params={"code": "the-code", "state": query["state"][0]},
        follow_redirects=False,
    )


def test_the_redirect_carries_pkce_state_and_nonce(
    google: dict[str, Any], make_client: type[TestClient]
) -> None:
    with make_client(create_app(), base_url=BASE) as browser:
        assert browser.get("/api/auth/providers").json() == {"google": True, "guest": True}
        start = browser.get("/api/auth/google/start", follow_redirects=False)
        url = urlparse(start.headers["location"])
        query = parse_qs(url.query)
        assert url.netloc == "accounts.google.com"
        assert query["code_challenge_method"] == ["S256"]
        assert query["redirect_uri"] == [f"{BASE}/api/auth/google/callback"]
        assert query["scope"] == ["openid email profile"]
        assert query["state"][0]
        assert query["nonce"][0]


def test_a_guest_signs_in_keeps_their_demo_and_resumes_elsewhere(
    google: dict[str, Any], make_client: type[TestClient]
) -> None:
    with make_client(create_app(), base_url=BASE) as browser:
        guest_ws = demo(browser)["workspace_id"]
        guest_cookie = browser.cookies.get(COOKIE)
        done = sign_in(browser, google)
        assert done.status_code == 303
        assert done.headers["location"] == "/home"
        assert browser.cookies.get(COOKIE) != guest_cookie  # rotated at sign-in
        me = browser.get("/api/session").json()
        assert me["workspace_id"] == guest_ws
        assert me["account"] == {
            "kind": "google",
            "name": "Amara Test",
            "email": "amara@example.com",
        }
        with make_client(create_app(), base_url=BASE) as replay:
            replay.cookies.set(COOKIE, str(guest_cookie))
            assert replay.get("/api/session").status_code == 401  # the guest session is revoked
    with make_client(create_app(), base_url=BASE) as laptop:
        assert sign_in(laptop, google).status_code == 303
        assert laptop.get("/api/session").json()["workspace_id"] == guest_ws


@pytest.mark.parametrize(
    "bad", [{"nonce": "wrong"}, {"aud": "someone-else"}, {"iss": "https://evil.example"}]
)
def test_a_token_that_doesnt_check_out_is_refused(
    google: dict[str, Any], make_client: type[TestClient], bad: dict[str, Any]
) -> None:
    google["claims"] = bad
    with make_client(create_app(), base_url=BASE) as browser:
        done = sign_in(browser, google)
        assert done.headers["location"] == "/?auth=failed"
        assert browser.get("/api/session").status_code == 401


def test_a_forged_state_and_an_unsafe_next_are_ignored(
    google: dict[str, Any], make_client: type[TestClient]
) -> None:
    with make_client(create_app(), base_url=BASE) as browser:
        browser.get("/api/auth/google/start", follow_redirects=False)
        forged = browser.get(
            "/api/auth/google/callback",
            params={"code": "the-code", "state": "x"},
            follow_redirects=False,
        )
        assert forged.headers["location"] == "/?auth=failed"
        demo(browser)
        done = sign_in(browser, google, next_path="//evil.example/steal")
        assert done.headers["location"] == "/home"
