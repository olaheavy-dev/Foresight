"""Proactive checked advice after a data change (review R2, owner decision 15 Oct 2026).

An import with new rows, a category correction or a declared balance queues one `analysis_job`
in the same transaction as the change (migration 0008), so a restart never loses it. Changes
close together collapse into the profile's single queued job. One worker thread runs each job
after a short quiet period:

- the deterministic findings are refreshed (no model, always);
- the checked-advice workflow (the existing graph: analyst → forecaster → risk check → Advisor ⇄
  Verifier) runs when AI is available and the profile has runs left today; otherwise the job is
  recorded as skipped with the reason, and Home says advice is paused.

Spend stays bounded: at most RUNS_PER_DAY event runs per profile (1 for a demo copy, started
only by its "Run the proactive check" button), inside the Mesh client's own daily cap.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.agents import findings
from backend.settings import get_settings
from backend.storage import models as m
from backend.storage.agent_repo import AgentStore
from backend.storage.db import session_factory
from backend.storage.ids import new_id
from backend.storage.repositories import WorkspaceContext

log = logging.getLogger(__name__)

WORKFLOWS = {
    "import_committed": "ingestion",  # new rows: categorise the uncertain ones first
    "category_corrected": "risk_detection",
    "balance_declared": "risk_detection",
    "manual_check": "risk_detection",  # a demo copy's "Run the proactive check"
}
DEBOUNCE = timedelta(seconds=30)
RUNS_PER_DAY = 2
DEMO_RUNS_PER_DAY = 1
POLL_SECONDS = 2.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(ctx: WorkspaceContext, event: str, *, immediate: bool = False) -> None:
    """Queue (or refresh) this profile's analysis job. The caller commits, so the job is written
    with the change that caused it. An import's workflow wins over a later correction's."""
    workflow = WORKFLOWS[event]
    ws = ctx.workspace
    not_before = utcnow() + (timedelta(0) if immediate else DEBOUNCE)
    table = m.AnalysisJob.__table__
    stmt = insert(m.AnalysisJob).values(
        id=new_id("job"),
        workspace_id=ws.id,
        event=event,
        workflow=workflow,
        data_version=int(ws.data_version or 0),
        status="queued",
        not_before=not_before,
    )
    keep_ingestion = table.c.workflow == "ingestion"
    stmt = stmt.on_conflict_do_update(
        index_elements=["workspace_id"],
        index_where=text("status = 'queued'"),
        set_={
            "data_version": stmt.excluded.data_version,
            "not_before": stmt.excluded.not_before,
            "workflow": case((keep_ingestion, table.c.workflow), else_=stmt.excluded.workflow),
            "event": case((keep_ingestion, table.c.event), else_=stmt.excluded.event),
        },
    )
    ctx.session.execute(stmt)


def runs_today(db: Session, workspace_id: str) -> int:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count: int | None = db.scalar(
        select(func.count())
        .select_from(m.AgentRun)
        .where(
            m.AgentRun.workspace_id == workspace_id,
            m.AgentRun.trigger == "event",
            m.AgentRun.started_at >= start,
        )
    )
    return int(count or 0)


def daily_allowance(ws: m.Workspace) -> int:
    return DEMO_RUNS_PER_DAY if ws.kind == "sample" else RUNS_PER_DAY


def advice_blocked(db: Session, ws: m.Workspace) -> str | None:
    """Why the checked-advice workflow can't run now, or None. Findings run regardless."""
    from backend.app.routers.ask import ai_status, get_mesh

    if ws.kind == "demo":
        return "template"
    if ai_status(get_mesh()) != "ok":
        return "ai_paused"
    if runs_today(db, ws.id) >= daily_allowance(ws):
        return "daily_limit"
    return None


def run_job(job_id: str, database_url: str) -> None:
    """Run one claimed job to completion (never raises; the outcome is recorded on the job)."""
    from backend.agents.runner import run_workflow
    from backend.app.routers.ask import get_mesh

    with session_factory(database_url)() as db:
        job = db.get(m.AnalysisJob, job_id)
        if job is None:
            return
        try:
            ctx = WorkspaceContext.open(db, job.workspace_id)
            findings.refresh(ctx)
            db.commit()
            blocked = advice_blocked(db, ctx.workspace)
            if blocked is None and ctx.workspace.kind == "sample" and job.event != "manual_check":
                # A demo copy runs advice only from its button (owner decision): an edit there
                # refreshes the findings but never spends on its own.
                blocked = "manual_only"
            if blocked is None:
                outcome = run_workflow(
                    AgentStore(ctx),
                    workflow=job.workflow,
                    trigger="event",
                    event=job.event,
                    mesh=get_mesh(),
                )
                job.run_id = outcome.run_id
                job.status = "done"
            else:
                job.status, job.note = "skipped", blocked
        except Exception as exc:  # noqa: BLE001 - recorded on the job, never kills the worker
            db.rollback()
            job = db.get(m.AnalysisJob, job_id)
            if job is None:
                return
            log.exception("proactive job %s failed", job_id)
            job.status, job.note = "failed", f"{type(exc).__name__}: {exc}"[:500]
        job.finished_at = utcnow()
        db.commit()


def claim(db: Session) -> str | None:
    """Take the next due job (SKIP LOCKED, so a second worker would never take the same one)."""
    due = (
        select(m.AnalysisJob.id)
        .where(m.AnalysisJob.status == "queued", m.AnalysisJob.not_before <= utcnow())
        .order_by(m.AnalysisJob.not_before)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    job_id = db.scalar(
        update(m.AnalysisJob)
        .where(m.AnalysisJob.id == due)
        .values(status="running", started_at=utcnow(), attempts=m.AnalysisJob.attempts + 1)
        .returning(m.AnalysisJob.id)
    )
    db.commit()
    return job_id


def recover(db: Session) -> int:
    """At start-up, jobs left `running` by a stopped process run again (one process owns jobs)."""
    count = db.execute(
        update(m.AnalysisJob)
        .where(m.AnalysisJob.status == "running")
        .values(status="queued", not_before=utcnow())
    ).rowcount
    db.commit()
    return int(count or 0)


def drain(database_url: str, *, limit: int = 100) -> int:
    """Run every job that is due now (tests, and each worker tick)."""
    done = 0
    while done < limit:
        with session_factory(database_url)() as db:
            job_id = claim(db)
        if job_id is None:
            return done
        run_job(job_id, database_url)
        done += 1
    return done


_worker: threading.Thread | None = None
_stop = threading.Event()


def start_worker() -> None:
    """One background worker per API process (started by the app lifespan)."""
    global _worker
    url = get_settings().database_url
    if not url or _worker is not None:
        return
    with session_factory(url)() as db:
        recovered = recover(db)
    if recovered:
        log.info("proactive: %d interrupted job(s) queued again", recovered)

    def loop() -> None:
        while not _stop.wait(POLL_SECONDS):
            try:
                drain(url)
            except Exception:  # noqa: BLE001 - keep polling; a bad tick is logged
                log.exception("proactive worker tick failed")

    _stop.clear()
    _worker = threading.Thread(target=loop, name="proactive-worker", daemon=True)
    _worker.start()


def stop_worker() -> None:
    global _worker
    _stop.set()
    _worker = None
