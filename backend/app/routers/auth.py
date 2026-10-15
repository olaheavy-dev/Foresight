"""Google sign-in (OpenID Connect authorization-code flow with PKCE; owner decision 15 Oct 2026).

`/api/auth/google/start` sends the browser to Google with a fresh `state`, `nonce` and PKCE
challenge, kept in a short-lived signed cookie. `/api/auth/google/callback` checks the state,
exchanges the code server-side, and validates the ID token against Google's published keys:
signature (RS256), issuer, audience, expiry and nonce. The person is identified by issuer +
subject, never by e-mail alone. Signing in rotates the session; a guest's profiles move to the
account, so nothing they did as a guest is lost.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update

from backend.app import session as sess
from backend.app.session import Db
from backend.settings import get_settings
from backend.storage import models as m
from backend.storage.ids import new_id

router = APIRouter(prefix="/api/auth", tags=["auth"])

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"  # noqa: S105 - an endpoint URL, not a secret
JWKS = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
FLOW_COOKIE = "foresight_oidc"
FLOW_SECONDS = 600
CALLBACK = "/api/auth/google/callback"


def configured() -> bool:
    s = get_settings()
    return bool(s.google_oauth_client_id and s.google_oauth_client_secret)


def _redirect_uri() -> str:
    return get_settings().public_base_url.rstrip("/") + CALLBACK


def _safe_next(value: str | None) -> str:
    """Only a same-site path: never an absolute URL or a protocol-relative one."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value[:200]
    return "/home"


def _flow_key() -> bytes:
    secret = get_settings().session_secret or get_settings().google_oauth_client_secret
    return hashlib.sha256(f"oidc-flow|{secret}".encode()).digest()


def _seal(data: dict[str, str]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(data, sort_keys=True).encode()).decode().rstrip("=")
    mac = hmac.new(_flow_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def _unseal(value: str | None) -> dict[str, str] | None:
    if not value or "." not in value:
        return None
    body, mac = value.rsplit(".", 1)
    expected = hmac.new(_flow_key(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


@router.get("/providers")
def providers() -> dict[str, bool]:
    """Which sign-in methods are available (the UI hides Google until it is configured)."""
    return {"google": configured(), "guest": True}


@router.get("/google/start")
def google_start(next: str | None = None) -> Response:  # noqa: A002 - the conventional name
    if not configured():
        return RedirectResponse("/?auth=unavailable", status_code=303)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    query = urlencode(
        {
            "client_id": get_settings().google_oauth_client_id,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    response = RedirectResponse(f"{AUTHORIZE}?{query}", status_code=303)
    response.set_cookie(
        FLOW_COOKIE,
        _seal({"state": state, "nonce": nonce, "verifier": verifier, "next": _safe_next(next)}),
        max_age=FLOW_SECONDS,
        httponly=True,
        samesite="lax",  # the return from Google is a top-level GET navigation
        secure=get_settings().session_cookie_secure,
        path="/api/auth",
    )
    return response


def exchange_code(code: str, verifier: str) -> dict[str, Any]:
    """The token endpoint call (server to server). Separate so tests can replace it."""
    s = get_settings()
    reply = httpx.post(
        TOKEN,
        data={
            "code": code,
            "client_id": s.google_oauth_client_id,
            "client_secret": s.google_oauth_client_secret,
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=10.0,
    )
    reply.raise_for_status()
    data = reply.json()
    if not isinstance(data, dict):
        raise ValueError("unexpected token response")
    return data


@lru_cache
def _jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(JWKS, cache_keys=True, lifespan=3600)


def signing_key(token: str) -> Any:
    """Google's public key for this token (cached JWKS). Separate so tests can replace it."""
    return _jwks().get_signing_key_from_jwt(token).key


def verify_id_token(token: str, nonce: str) -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(
        token,
        signing_key(token),
        algorithms=["RS256"],
        audience=get_settings().google_oauth_client_id,
        issuer=list(ISSUERS),
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        leeway=60,
    )
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise jwt.InvalidTokenError("nonce mismatch")
    return claims


def _failed(reason: str) -> Response:
    response = RedirectResponse(f"/?auth={reason}", status_code=303)
    response.delete_cookie(FLOW_COOKIE, path="/api/auth")
    return response


@router.get("/google/callback")
def google_callback(
    request: Request, db: Db, code: str | None = None, state: str | None = None
) -> Response:
    flow = _unseal(request.cookies.get(FLOW_COOKIE))
    if not configured() or not flow or not state or not code:
        return _failed("failed")
    if not hmac.compare_digest(flow.get("state", ""), state):
        return _failed("failed")
    try:
        tokens = exchange_code(code, flow["verifier"])
        claims = verify_id_token(str(tokens.get("id_token", "")), flow["nonce"])
    except (httpx.HTTPError, jwt.PyJWTError, ValueError, KeyError):
        return _failed("failed")
    if claims.get("email") and claims.get("email_verified") is False:
        return _failed("unverified")

    issuer, subject = str(claims["iss"]), str(claims["sub"])
    user = db.scalars(
        select(m.AppUser).where(m.AppUser.issuer == issuer, m.AppUser.subject == subject)
    ).first()
    if user is None:
        user = m.AppUser(id=new_id("usr"), issuer=issuer, subject=subject)
        db.add(user)
    user.email = str(claims.get("email") or "")[:320] or None
    user.name = str(claims.get("name") or "")[:200] or None
    user.last_login_at = sess.utcnow()
    db.flush()

    guest = sess.current(request, db)
    active: str | None = None
    if guest is not None:
        if guest.user_id is None:
            # A guest's profiles become the account's: nothing done as a guest is lost.
            db.execute(
                update(m.Workspace)
                .where(m.Workspace.owner_session_id == guest.id)
                .values(owner_user_id=user.id, owner_session_id=None)
            )
        active = guest.active_workspace_id
        sess.revoke(db, guest)
    response = RedirectResponse(flow.get("next") or "/home", status_code=303)
    fresh = sess.start(db, response, user_id=user.id)  # rotate: a new token at sign-in
    owned = sess.owned_workspaces(db, fresh)
    if active not in {w.id for w in owned}:
        active = owned[-1].id if owned else None
    fresh.active_workspace_id = active
    db.commit()
    if active is None:
        response.headers["location"] = "/?auth=signedin"
    response.delete_cookie(FLOW_COOKIE, path="/api/auth")
    return response
