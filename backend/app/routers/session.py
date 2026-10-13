"""Choose a profile: the seeded demo or a new empty one (see backend/app/session.py)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status

from backend.app.session import Db, Profile, set_profile_cookie
from backend.app.ui_contracts.response import ProfileView
from backend.storage import models as m
from backend.storage.repositories import create_workspace, demo_workspace

router = APIRouter(prefix="/api/session", tags=["session"])


def profile_view(ws: m.Workspace) -> ProfileView:
    return ProfileView(
        workspace_id=ws.id,
        name=ws.name,
        kind="demo" if ws.kind == "demo" else "user",
        persona=ws.persona_key,
        country=ws.country,
        home_currency=ws.home_currency,
        locale=ws.locale,
        timezone=ws.timezone,
        data_version=ws.data_version,
        read_only=ws.kind == "demo",
    )


@router.post("/demo", response_model=ProfileView)
def use_demo(session: Db, response: Response, persona: Literal["P1", "P2"] = "P1") -> ProfileView:
    ws = demo_workspace(session, persona)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The demo profile hasn't been set up yet.")
    set_profile_cookie(response, ws.id)
    return profile_view(ws)


@router.post("/new", response_model=ProfileView, status_code=status.HTTP_201_CREATED)
def new_profile(session: Db, response: Response) -> ProfileView:
    """A fresh UK profile (GBP) to import statements into. Other locales arrive with Stage 4."""
    ctx = create_workspace(
        session,
        name="My profile",
        country="GB",
        home_currency="GBP",
        locale="en-GB",
        timezone_name="Europe/London",
    )
    ws = ctx.workspace
    session.commit()
    set_profile_cookie(response, ws.id)
    return profile_view(ws)


@router.get("", response_model=ProfileView)
def current(ctx: Profile) -> ProfileView:
    return profile_view(ctx.workspace)
