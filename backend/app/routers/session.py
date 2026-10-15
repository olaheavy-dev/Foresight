"""Choose a profile, sign out, delete my data (see backend/app/session.py).

- `POST /api/session/demo?persona=P1` gives this browser a private copy of the demo (a guest
  session is started if there is none). Visitors never share a demo workspace.
- `POST /api/session/new` creates an empty profile of its own for statement imports.
- `POST /api/session/logout` ends the session; `POST /api/session/delete` deletes every profile
  the session or user owns, then ends it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, or_, text

from backend.app import session as sess
from backend.app.session import Db, Profile
from backend.app.ui_contracts.response import ProfileView, SessionAccount
from backend.pipeline.seed_demo import PERSONAS, dataset_root, seed_persona
from backend.storage import models as m
from backend.storage.repositories import create_workspace

router = APIRouter(prefix="/api/session", tags=["session"])
ORPHAN_GRACE = timedelta(days=1)


def account_view(db: Db, row: m.AuthSession | None) -> SessionAccount | None:
    if row is None:
        return None
    if row.user_id is None:
        return SessionAccount(kind="guest")
    user = db.get(m.AppUser, row.user_id)
    return SessionAccount(
        kind="google", name=user.name if user else None, email=user.email if user else None
    )


def profile_view(ws: m.Workspace, account: SessionAccount | None = None) -> ProfileView:
    return ProfileView(
        workspace_id=ws.id,
        name=ws.name,
        kind="demo" if ws.kind in sess.READ_ONLY_KINDS else "user",
        persona=ws.persona_key,
        country=ws.country,
        home_currency=ws.home_currency,
        locale=ws.locale,
        timezone=ws.timezone,
        data_version=ws.data_version,
        read_only=sess.read_only(ws),
        account=account,
    )


def allow_purge(db: Db) -> None:
    """FR-72 hard delete: this transaction may delete from the append-only tables (the audit
    chain goes with the workspace); the setting ends with the transaction."""
    db.execute(text("SET LOCAL foresight.purge = 'on'"))


def purge_expired(db: Db) -> int:
    """Delete guest data nobody can open any more: expired or revoked guest sessions (their
    workspaces cascade) and non-template workspaces left without an owner. Cheap; runs when a
    new guest starts."""
    now = sess.utcnow()
    allow_purge(db)
    gone = db.execute(
        delete(m.AuthSession).where(
            m.AuthSession.user_id.is_(None),
            or_(m.AuthSession.expires_at <= now, m.AuthSession.revoked_at.is_not(None)),
        )
    ).rowcount
    orphans = db.execute(
        delete(m.Workspace).where(
            m.Workspace.kind != "demo",
            m.Workspace.owner_user_id.is_(None),
            m.Workspace.owner_session_id.is_(None),
            m.Workspace.created_at <= now - ORPHAN_GRACE,
        )
    ).rowcount
    return int(gone or 0) + int(orphans or 0)


@router.post("/demo", response_model=ProfileView)
def use_demo(
    request: Request, response: Response, db: Db, persona: Literal["P1", "P2"] = "P1"
) -> ProfileView:
    """This browser's private copy of the fictional demo: reused if it has one, else seeded
    (deterministic, no model call)."""
    row = sess.current(request, db)
    if row is None:
        purge_expired(db)
        row = sess.start(db, response)
    copy = next(
        (
            w
            for w in sess.owned_workspaces(db, row)
            if w.kind == "sample" and w.persona_key == persona
        ),
        None,
    )
    if copy is None:
        spec = next(p for p in PERSONAS if p.key == persona)
        report = seed_persona(db, dataset_root(), spec, owner=sess.owner_fields(row))
        copy = db.get(m.Workspace, report.workspace_id)
        if copy is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "The demo couldn't be prepared."
            )
    row.active_workspace_id = copy.id
    db.commit()
    return profile_view(copy, account_view(db, row))


@router.post("/new", response_model=ProfileView, status_code=status.HTTP_201_CREATED)
def new_profile(request: Request, response: Response, db: Db) -> ProfileView:
    """A fresh UK profile (GBP) of this browser's or user's own, to import statements into."""
    row = sess.current(request, db)
    if row is None:
        purge_expired(db)
        row = sess.start(db, response)
    owner = sess.owner_fields(row)
    ctx = create_workspace(
        db,
        name="My profile",
        country="GB",
        home_currency="GBP",
        locale="en-GB",
        timezone_name="Europe/London",
        owner_user_id=owner["owner_user_id"],
        owner_session_id=owner["owner_session_id"],
    )
    row.active_workspace_id = ctx.workspace.id
    db.commit()
    return profile_view(ctx.workspace, account_view(db, row))


@router.get("", response_model=ProfileView)
def current(request: Request, ctx: Profile, db: Db) -> ProfileView:
    return profile_view(ctx.workspace, account_view(db, sess.current(request, db)))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Db) -> None:
    """End this session. A guest's data stays until it expires (or use delete)."""
    row = sess.current(request, db)
    if row is not None:
        sess.revoke(db, row)
        db.commit()
    sess.clear_cookie(response)


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_data(request: Request, response: Response, db: Db) -> None:
    """Delete every profile this session (or its user) owns, with all their data, and the user
    record; then end the session (docs/01 F-53)."""
    row = sess.current(request, db)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "There is no session to delete.")
    allow_purge(db)
    for ws in sess.owned_workspaces(db, row):
        db.delete(ws)
    if row.user_id:
        db.execute(delete(m.AuthSession).where(m.AuthSession.user_id == row.user_id))
        db.execute(delete(m.AppUser).where(m.AppUser.id == row.user_id))
    else:
        db.execute(delete(m.AuthSession).where(m.AuthSession.id == row.id))
    db.commit()
    sess.clear_cookie(response)
