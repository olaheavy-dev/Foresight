from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.storage import models as m
from backend.storage.ids import new_id
from backend.storage.repositories import WorkspaceContext, create_workspace

DATASETS = Path(__file__).resolve().parents[3] / "evals" / "datasets"


def dataset(name: str) -> dict[str, Any]:
    folder = DATASETS / name
    return {
        "workspace": json.loads((folder / "workspace.json").read_text()),
        "account": json.loads((folder / "truth_accounts.json").read_text())["accounts"][0],
        "folder": folder,
    }


def export(name: str) -> tuple[str, bytes]:
    path = DATASETS / name / dataset(name)["account"]["file"]
    return path.name, path.read_bytes()


def workspace_with_account(
    session: Session, name: str = "Test", buffer_minor: int | None = None
) -> tuple[WorkspaceContext, str]:
    ctx = create_workspace(
        session, name=name, country="GB", home_currency="GBP", locale="en-GB",
        timezone_name="Europe/London", buffer_minor=buffer_minor,
    )  # fmt: skip
    acct = m.Account(id=new_id("acct"), name="Current account", currency="GBP")
    ctx.add(acct)
    session.flush()
    return ctx, acct.id


def count(ctx: WorkspaceContext, model: type[m.Base]) -> int:
    column = model.__table__.c.workspace_id
    return int(
        ctx.session.scalar(
            select(func.count()).select_from(model).where(column == ctx.workspace_id)
        )
        or 0
    )
