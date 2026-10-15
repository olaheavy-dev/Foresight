"""A warm pool of private demo copies (R1 follow-up, 15 Oct 2026).

Seeding a guest's private copy of the fictional demo is CPU work (CSV parse, categorisation and a
forecast: about 2.5 s), and in the single API process it slowed every other request while it ran.
So copies are seeded ahead of time in one separate worker process and kept unowned (kind
`sample`, no owner, so they never open in a browser). "Explore the live demo" claims one with
`FOR UPDATE SKIP LOCKED`, which is instant. The entrypoint fills the pool before the API serves,
and refills wait until claims have been quiet for REFILL_DELAY_SECONDS: a seed is a burst of
database writes, and running it while a guest loads their first pages made those pages time out
on a small machine. If the pool is empty, the request waits for the worker (the guest sees
"Opening the demo…") rather than seeding in the API process.

`DEMO_POOL_SIZE=0` turns the pool off and seeds inline (tests).
"""

from __future__ import annotations

import logging
import multiprocessing
import threading
from concurrent.futures import Future, ProcessPoolExecutor

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.pipeline.seed_demo import PERSONAS, dataset_root, seed_persona
from backend.settings import get_settings
from backend.storage import models as m

log = logging.getLogger(__name__)
SEED_WAIT_SECONDS = 60
REFILL_DELAY_SECONDS = 60.0
POOLED = ("P1",)  # the persona "Explore the live demo" opens; others seed on demand
UNOWNED = {"owner_user_id": None, "owner_session_id": None}

_lock = threading.Lock()
_executor: ProcessPoolExecutor | None = None
_pending: dict[str, int] = {}
_refills: dict[str, threading.Timer] = {}


def enabled() -> bool:
    return get_settings().demo_pool_size > 0 and bool(get_settings().database_url)


def seed_unowned(database_url: str, persona: str) -> str:
    """Runs in the worker process: one unowned private copy, committed."""
    from backend.storage.db import session_factory

    spec = next(p for p in PERSONAS if p.key == persona)
    with session_factory(database_url)() as db:
        report = seed_persona(db, dataset_root(), spec, owner=dict(UNOWNED))
        db.commit()
        return report.workspace_id


def _pool() -> ProcessPoolExecutor:
    global _executor
    if _executor is None:
        # spawn: never fork a process that has threads (the API's thread pool, ask streams).
        _executor = ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn")
        )
    return _executor


def _submit(persona: str) -> Future[str]:
    _pending[persona] = _pending.get(persona, 0) + 1

    def done(fut: Future[str]) -> None:
        with _lock:
            _pending[persona] -= 1
        if fut.exception() is not None:
            log.warning("demo pool: seeding %s failed: %s", persona, fut.exception())

    fut = _pool().submit(seed_unowned, get_settings().database_url, persona)
    fut.add_done_callback(done)
    return fut


def _unowned(persona: str) -> Select[tuple[m.Workspace]]:
    return select(m.Workspace).where(
        m.Workspace.kind == "sample",
        m.Workspace.persona_key == persona,
        m.Workspace.owner_user_id.is_(None),
        m.Workspace.owner_session_id.is_(None),
    )


def top_up(db: Session, persona: str) -> None:
    """Queue enough seeds to bring the pool back to DEMO_POOL_SIZE (never blocks)."""
    if not enabled():
        return
    ready = db.scalar(select(func.count()).select_from(_unowned(persona).subquery())) or 0
    with _lock:
        for _ in range(get_settings().demo_pool_size - ready - _pending.get(persona, 0)):
            _submit(persona)


def claim(db: Session, persona: str, owner: dict[str, str | None]) -> m.Workspace | None:
    """Give one pooled copy to `owner` (the caller commits). Waits for the worker if the pool is
    empty; seeds inline only when the pool is turned off."""
    if not enabled():
        spec = next(p for p in PERSONAS if p.key == persona)
        report = seed_persona(db, dataset_root(), spec, owner=owner)
        seeded: m.Workspace | None = db.get(m.Workspace, report.workspace_id)
        return seeded
    stmt = _unowned(persona).order_by(m.Workspace.created_at).limit(1)
    ws = db.scalars(stmt.with_for_update(skip_locked=True)).first()
    if ws is None:
        with _lock:
            fut = _submit(persona)
        fresh = fut.result(timeout=SEED_WAIT_SECONDS)
        stmt = _unowned(persona).where(m.Workspace.id == fresh)
        ws = db.scalars(stmt.with_for_update(skip_locked=True)).first()
    if ws is None:
        return None
    ws.owner_user_id = owner["owner_user_id"]
    ws.owner_session_id = owner["owner_session_id"]
    return ws


def schedule_refill(persona: str) -> None:
    """Top the pool up once claims have been quiet for REFILL_DELAY_SECONDS (debounced)."""
    if not enabled() or persona not in POOLED:
        return

    def refill() -> None:
        from backend.storage.db import session_factory

        try:
            with session_factory(get_settings().database_url)() as db:
                top_up(db, persona)
        except Exception:  # noqa: BLE001 - the next claim tries again
            log.exception("demo pool: refill failed")

    with _lock:
        if (old := _refills.get(persona)) is not None:
            old.cancel()
        timer = threading.Timer(REFILL_DELAY_SECONDS, refill)
        timer.daemon = True
        _refills[persona] = timer
        timer.start()


def warm(db: Session) -> None:
    """Queue whatever the pool is missing (start-up, after the entrypoint's fill)."""
    for persona in POOLED:
        top_up(db, persona)


def fill(database_url: str, size: int) -> int:
    """Seed the pool in this process until it is full (the entrypoint, before the API serves)."""
    from backend.storage.db import session_factory

    made = 0
    for persona in POOLED:
        with session_factory(database_url)() as db:
            ready = db.scalar(select(func.count()).select_from(_unowned(persona).subquery())) or 0
        for _ in range(size - ready):
            seed_unowned(database_url, persona)
            made += 1
    return made


if __name__ == "__main__":
    settings = get_settings()
    if settings.demo_pool_size > 0 and settings.database_url:
        print(f"demo pool: seeded {fill(settings.database_url, settings.demo_pool_size)} copies")
