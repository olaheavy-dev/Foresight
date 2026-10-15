"""Seed the demo workspaces from the generated datasets (DEMO-01).

P1 (Monzo CSV plus the declared balance from the dataset's workspace.json) and P2 (generic CSV with
a running balance) go through the real importers, detection and a baseline forecast. Running it
again changes nothing: the imports dedupe, the declared balance is unchanged and the forecast maps
to the same calculation.

    python -m backend.pipeline.seed_demo

Dataset root: $FORESIGHT_DEMO_DATA, else evals/datasets in the source tree.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.pipeline.forecast import run_forecast
from backend.pipeline.ingest import declare_balance, ingest_file
from backend.storage import models as m
from backend.storage.ids import new_id
from backend.storage.repositories import WorkspaceContext, create_workspace, demo_workspace

log = logging.getLogger("foresight.seed_demo")

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "evals" / "datasets"


@dataclass(frozen=True)
class Persona:
    key: str  # P1, P2
    dataset: str


PERSONAS = (Persona("P1", "P1-base"), Persona("P2", "P2-base"))


@dataclass(frozen=True)
class SeedReport:
    persona: str
    workspace_id: str
    created: bool
    new_rows: int
    forecast_id: str
    forecast_created: bool


class SeedError(RuntimeError):
    pass


def dataset_root() -> Path:
    return Path(os.environ.get("FORESIGHT_DEMO_DATA") or DEFAULT_ROOT)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def seed_persona(
    session: Session,
    root: Path,
    persona: Persona,
    *,
    owner: dict[str, str | None] | None = None,
) -> SeedReport:
    """Seed a persona: the shared template (kind `demo`, idempotent) or, with `owner`, a new
    private `sample` copy for one guest or user (docs/05 §5.9). Same files, same engine."""
    folder = root / persona.dataset
    spec = _read_json(folder / "workspace.json")
    accounts = _read_json(folder / "truth_accounts.json")["accounts"]

    existing = None if owner else demo_workspace(session, persona.key)
    if existing is None:
        ctx = create_workspace(
            session,
            name=spec["display_name"],
            country=spec["country"],
            home_currency=spec["home_currency"],
            locale=spec["locale"],
            timezone_name=spec["timezone"],
            kind="sample" if owner else "demo",
            persona_key=persona.key,
            buffer_minor=spec.get("buffer_minor"),
            **(owner or {}),
        )
    else:
        ctx = WorkspaceContext.open(session, existing.id)

    account_ids: dict[str, str] = {}
    new_rows = 0
    for acct in accounts:
        source_key = f"demo:{persona.dataset}:{acct['id']}"
        row = ctx.account_by_source_key(source_key)
        if row is None:
            row = m.Account(
                id=new_id("acct"),
                name=acct["label"],
                institution=acct.get("institution"),
                currency=acct["currency"],
                currency_source="profile",
                source_key=source_key,
            )
            ctx.add(row)
            session.flush()
        account_ids[acct["id"]] = row.id
        path = folder / acct["file"]
        outcome = ingest_file(ctx, path.name, path.read_bytes(), account_id=row.id, actor="system")
        if outcome.status not in ("committed", "already_imported"):
            raise SeedError(f"{persona.dataset}/{acct['file']}: {outcome.status} {outcome.message}")
        new_rows += outcome.new_rows

    declared = spec.get("declared_balance")
    if declared:
        declare_balance(
            ctx,
            account_ids[declared["account"]],
            date.fromisoformat(declared["as_of"]),
            int(declared["amount_minor"]),
            source="demo_seed",
            actor="system",
        )
    forecast = run_forecast(ctx, as_of=date.fromisoformat(spec["as_of"]))
    return SeedReport(
        persona.key,
        ctx.workspace_id,
        existing is None,
        new_rows,
        forecast.calculation.id,
        forecast.created,
    )


def seed_all(session: Session, root: Path | None = None) -> list[SeedReport]:
    root = root or dataset_root()
    reports = []
    for persona in PERSONAS:
        try:
            reports.append(seed_persona(session, root, persona))
            session.commit()
        except Exception:
            session.rollback()
            raise
    return reports


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from backend.settings import get_settings
    from backend.storage.db import session_factory

    url = get_settings().database_url
    if not url:
        log.error("DATABASE_URL is not set")
        return 1
    root = dataset_root()
    if not (root / PERSONAS[0].dataset).is_dir():
        log.error("demo datasets not found at %s", root)
        return 1
    with session_factory(url)() as session:
        for r in seed_all(session, root):
            log.info(
                "%s %s: workspace %s, %d new rows, forecast %s%s",
                r.persona,
                "created" if r.created else "up to date",
                r.workspace_id,
                r.new_rows,
                r.forecast_id,
                "" if r.forecast_created else " (unchanged)",
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
