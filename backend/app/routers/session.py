"""Choose a profile, sign out, delete my data (see backend/app/session.py).

- `POST /api/session/demo?persona=P1` gives this browser a private copy of the demo (a guest
  session is started if there is none). Visitors never share a demo workspace.
- `POST /api/session/demo/reset` swaps that private copy for a fresh one.
- `POST /api/session/new` creates an empty profile of its own for statement imports.
- `POST /api/session/logout` ends the session (a guest's profiles are deleted with it);
  `POST /api/session/delete` deletes every profile the session or user owns, then ends it.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, or_, text, update

from backend.app import demo_pool
from backend.app import session as sess
from backend.app.session import Db, Profile
from backend.app.ui_contracts.response import ProfileView, SessionAccount
from backend.storage import models as m
from backend.storage.repositories import create_workspace

router = APIRouter(prefix="/api/session", tags=["session"])


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
        kind="demo" if ws.kind in sess.FICTIONAL_KINDS else "user",
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
    """Delete expired or revoked guest sessions; their workspaces go with them (ON DELETE
    CASCADE). Ownerless workspaces are never deleted here: they are the warm demo pool or
    profiles from before accounts (migration 0007), which a returning browser can still adopt
    (session.adopt_legacy). Cheap; runs when a new guest starts."""
    now = sess.utcnow()
    allow_purge(db)
    gone = db.execute(
        delete(m.AuthSession).where(
            m.AuthSession.user_id.is_(None),
            or_(m.AuthSession.expires_at <= now, m.AuthSession.revoked_at.is_not(None)),
        )
    ).rowcount
    return int(gone or 0)


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
        try:
            copy = demo_pool.claim(db, persona, sess.owner_fields(row))
        except TimeoutError:
            copy = None
        if copy is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "The demo couldn't be prepared. Try again."
            )
        copy.last_active_at = sess.utcnow()
    row.active_workspace_id = copy.id
    db.commit()
    demo_pool.schedule_refill(persona)
    return profile_view(copy, account_view(db, row))


@router.post("/demo/reset", response_model=ProfileView)
def reset_demo(request: Request, db: Db) -> ProfileView:
    """Swap this session's private demo copy (the active profile) for a fresh one: categories,
    balances and conversations go back to the start. Other visitors are never affected."""
    row = sess.current(request, db)
    ws = db.get(m.Workspace, row.active_workspace_id) if row and row.active_workspace_id else None
    if row is None or ws is None or ws.kind != "sample" or not sess.owns(row, ws):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a demo profile can be reset.")
    persona = ws.persona_key or "P1"
    try:
        fresh = demo_pool.claim(db, persona, sess.owner_fields(row))
    except TimeoutError:
        fresh = None
    if fresh is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "A fresh demo couldn't be prepared. Try again."
        )
    fresh.last_active_at = sess.utcnow()
    # Every copy of this persona the owner has goes, not just the active one: an account can hold
    # two (a guest copy moved in at sign-in), and /demo would reopen the older edited one.
    stale = [
        w
        for w in sess.owned_workspaces(db, row)
        if w.kind == "sample" and w.persona_key == persona and w.id != fresh.id
    ]
    gone = {w.id for w in stale}
    # Other browsers of the same account that had a removed copy open move to the fresh one.
    db.execute(
        update(m.AuthSession)
        .where(m.AuthSession.active_workspace_id.in_(gone))
        .values(active_workspace_id=fresh.id)
    )
    row.active_workspace_id = fresh.id
    allow_purge(db)
    for w in stale:
        db.delete(w)
    db.commit()
    demo_pool.schedule_refill(persona)
    return profile_view(fresh, account_view(db, row))


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
    """End this session. A signed-in user's profiles stay with the account. A guest's can never be
    opened again once the cookie is gone, so they're deleted now, not left until a purge runs
    (the privacy page promises this)."""
    row = sess.current(request, db)
    if row is not None:
        if row.user_id is None:
            allow_purge(db)
            for ws in sess.owned_workspaces(db, row):
                db.delete(ws)
            db.delete(row)
        else:
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
