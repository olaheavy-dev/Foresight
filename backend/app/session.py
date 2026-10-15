"""Browser sessions, accounts and workspace ownership (docs/05 §5.9; owner decision 15 Oct 2026).

A browser holds one opaque random token in the `foresight_session` cookie (Secure, HttpOnly,
SameSite=Lax); only its SHA-256 is stored. A session is a guest (no user) or a signed-in Google
user, and names its active workspace. Every request resolves session → ownership → workspace:

- a workspace owned by a user opens for any live session of that user;
- a workspace owned by a guest session opens only for that session;
- seeded demo templates (kind `demo`) have no owner and never open in a browser; "Explore the
  demo" gives each guest a private `sample` copy, so visitors never share conversations or limits.
  A copy accepts category corrections and balances (they only affect its owner) but never imports,
  and "Reset demo" swaps it for a fresh one.

There is deliberately no header or query parameter that selects a workspace by id. State-changing
API calls must carry the `X-Foresight-Client` header (CSRF: a cross-site page cannot set a custom
header on a same-origin request, and the API sends no CORS headers).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.settings import get_settings
from backend.storage import models as m
from backend.storage.db import session_factory
from backend.storage.ids import new_id
from backend.storage.repositories import WorkspaceContext, WorkspaceNotFound

COOKIE = "foresight_session"
LEGACY_COOKIE = "foresight_profile"  # before accounts: a signed workspace id (migration 0007)
CSRF_HEADER = "X-Foresight-Client"
GUEST_IDLE = timedelta(days=7)  # a guest's private demo and imports expire after a week unused
USER_IDLE = timedelta(days=30)
TOUCH_EVERY = timedelta(minutes=5)
FICTIONAL_KINDS = frozenset(
    {"demo", "sample"}
)  # the demo persona: never mixed with real statements
READ_ONLY_KINDS = frozenset(
    {"demo"}
)  # the shared template; a guest's private `sample` copy is editable


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def db_session() -> Iterator[Session]:
    url = get_settings().database_url
    if not url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The database is not configured.")
    with session_factory(url)() as session:
        yield session


Db = Annotated[Session, Depends(db_session)]


def _set_cookie(response: Response, token: str, lifetime: timedelta) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=get_settings().session_cookie_secure,
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def current(request: Request, db: Session) -> m.AuthSession | None:
    """The live session named by the cookie, or None (no cookie, unknown, expired or revoked)."""
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 200:
        return None
    row = db.scalars(
        select(m.AuthSession).where(m.AuthSession.token_hash == token_hash(token))
    ).first()
    now = utcnow()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None
    if now - row.last_seen_at >= TOUCH_EVERY:
        # Sliding expiry, written at most every few minutes.
        row.last_seen_at = now
        row.expires_at = now + (USER_IDLE if row.user_id else GUEST_IDLE)
        db.commit()
    return row


def start(db: Session, response: Response, *, user_id: str | None = None) -> m.AuthSession:
    """A new session with a fresh random token, set as the cookie."""
    token = secrets.token_urlsafe(32)
    lifetime = USER_IDLE if user_id else GUEST_IDLE
    row = m.AuthSession(
        id=new_id("ses"),
        token_hash=token_hash(token),
        user_id=user_id,
        last_seen_at=utcnow(),
        expires_at=utcnow() + lifetime,
    )
    db.add(row)
    db.flush()
    _set_cookie(response, token, lifetime)
    return row


def ensure(request: Request, response: Response, db: Session) -> m.AuthSession:
    """The browser's live session, a pre-accounts one it can adopt, or a new guest session."""
    return current(request, db) or adopt_legacy(request, response, db) or start(db, response)


def revoke(db: Session, row: m.AuthSession) -> None:
    row.revoked_at = utcnow()


def owns(row: m.AuthSession, ws: m.Workspace) -> bool:
    if ws.owner_user_id is not None:
        return row.user_id == ws.owner_user_id
    return ws.owner_session_id is not None and ws.owner_session_id == row.id


def owner_fields(row: m.AuthSession) -> dict[str, str | None]:
    """Who a new workspace belongs to: the user when signed in, else this guest session."""
    if row.user_id:
        return {"owner_user_id": row.user_id, "owner_session_id": None}
    return {"owner_user_id": None, "owner_session_id": row.id}


def owned_workspaces(db: Session, row: m.AuthSession) -> list[m.Workspace]:
    if row.user_id:
        stmt = select(m.Workspace).where(m.Workspace.owner_user_id == row.user_id)
    else:
        stmt = select(m.Workspace).where(m.Workspace.owner_session_id == row.id)
    return list(db.scalars(stmt.order_by(m.Workspace.created_at)))


def _legacy_workspace_id(request: Request) -> str | None:
    """The workspace named by a pre-accounts `foresight_profile` cookie, if its signature checks
    (HMAC-SHA256 with SESSION_SECRET, as that cookie was issued)."""
    value = request.cookies.get(LEGACY_COOKIE)
    secret = get_settings().session_secret
    if not value or not secret or len(value) > 200:
        return None
    workspace_id, _, _ = value.partition(".")
    mac = hmac.new(secret.encode("utf-8"), workspace_id.encode("utf-8"), hashlib.sha256).digest()
    expected = f"{workspace_id}.{base64.urlsafe_b64encode(mac).decode('ascii').rstrip('=')}"
    return workspace_id if workspace_id and hmac.compare_digest(expected, value) else None


def adopt_legacy(request: Request, response: Response, db: Session) -> m.AuthSession | None:
    """A browser returning with a pre-accounts cookie keeps its profile: if that workspace has
    no owner yet, a new guest session takes it over (and the old cookie is dropped)."""
    workspace_id = _legacy_workspace_id(request)
    if workspace_id is None:
        return None
    ws = db.get(m.Workspace, workspace_id)
    if ws is None or ws.kind in FICTIONAL_KINDS or ws.owner_user_id or ws.owner_session_id:
        return None
    row = start(db, response)
    ws.owner_session_id = row.id
    row.active_workspace_id = ws.id
    db.commit()
    response.delete_cookie(LEGACY_COOKIE, path="/")
    return row


def workspace(request: Request, response: Response, db: Db) -> WorkspaceContext:
    row = current(request, db) or adopt_legacy(request, response, db)
    if row is None or row.active_workspace_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Choose a profile first: explore the demo or import a statement.",
        )
    ws = db.get(m.Workspace, row.active_workspace_id)
    if ws is None or not owns(row, ws):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "This profile isn't available. Choose a profile again."
        )
    now = utcnow()
    if ws.last_active_at is None or now - ws.last_active_at >= TOUCH_EVERY:
        ws.last_active_at = now
        db.commit()
    try:
        return WorkspaceContext.open(db, ws.id)
    except WorkspaceNotFound:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "This profile no longer exists. Choose a profile again."
        ) from None


def read_only(ws: m.Workspace) -> bool:
    """Edits refused: only the shared demo template (which never opens in a browser)."""
    return ws.kind in READ_ONLY_KINDS


def imports_refused(ws: m.Workspace) -> bool:
    """Real statements never go into the fictional demo persona, private copy or not: the
    forecast would mix real and made-up data and the "Demo data" label would be untrue."""
    return ws.kind in FICTIONAL_KINDS


Profile = Annotated[WorkspaceContext, Depends(workspace)]
