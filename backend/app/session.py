"""The profile session: a signed cookie naming one workspace (docs/05 §5.9, §7.2).

Stage 1 has no sign-in. A browser gets a workspace in one of two ways:
- `POST /api/session/demo?persona=P1` selects a seeded demo workspace (read-only: imports refused);
- `POST /api/session/new` creates a fresh, empty workspace of its own for CSV import.

The cookie holds `<workspace_id>.<HMAC-SHA256>`, so a client cannot name someone else's workspace:
there is deliberately no header or query parameter that selects a workspace by id.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.settings import get_settings
from backend.storage.db import session_factory
from backend.storage.repositories import WorkspaceContext, WorkspaceNotFound

COOKIE = "foresight_profile"
MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_process_secret = secrets.token_bytes(32)


def _secret() -> bytes:
    configured = get_settings().session_secret
    return configured.encode("utf-8") if configured else _process_secret


def sign(workspace_id: str) -> str:
    mac = hmac.new(_secret(), workspace_id.encode("utf-8"), hashlib.sha256).digest()
    return f"{workspace_id}.{base64.urlsafe_b64encode(mac).decode('ascii').rstrip('=')}"


def unsign(value: str) -> str | None:
    workspace_id, _, _ = value.partition(".")
    if workspace_id and hmac.compare_digest(sign(workspace_id), value):
        return workspace_id
    return None


def set_profile_cookie(response: Response, workspace_id: str) -> None:
    response.set_cookie(
        COOKIE,
        sign(workspace_id),
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=get_settings().session_cookie_secure,
        path="/",
    )


def db_session() -> Iterator[Session]:
    url = get_settings().database_url
    if not url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The database is not configured.")
    with session_factory(url)() as session:
        yield session


Db = Annotated[Session, Depends(db_session)]


def workspace(request: Request, session: Db) -> WorkspaceContext:
    raw = request.cookies.get(COOKIE)
    workspace_id = unsign(raw) if raw else None
    if workspace_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Choose a profile first: explore the demo or start a new profile.",
        )
    try:
        return WorkspaceContext.open(session, workspace_id)
    except WorkspaceNotFound:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "This profile no longer exists. Choose a profile again."
        ) from None


Profile = Annotated[WorkspaceContext, Depends(workspace)]
