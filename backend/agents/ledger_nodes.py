"""Graph nodes for the Ledger Agent and the Behaviour Analyst (docs/06 §4.1, §4.2, §8 W1/W5),
plus the ING-13 format-proposal run (docs/06 §9 H1, docs/09 ORC-15).

- `ledger`: the model fallback over rows the rules left below 0.85, as new append-only
  categorisations; confident answers teach merchant memory. Runs in W1 after an import.
- `ledger_query`: a deterministic, reproducible transaction query for `transaction_lookup`.
- `analyst`: deterministic finding candidates, then one reasoning-tier call to rank and word them.

With no model client the nodes still do their deterministic part and make no model call.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from backend.agents import analyst as an
from backend.agents import findings as fd
from backend.agents import format_profile as fp
from backend.agents import ledger as lg
from backend.agents.runtime import NodeOutput, NodeSpec, RunContext, deadline_for, instrument
from backend.agents.state import ForesightState
from backend.finance_core.calc import record
from backend.finance_core.categorise.rules import learn
from backend.finance_core.importers import blocking_questions, import_file
from backend.finance_core.importers.profiles import FormatProfile
from backend.llm.client import ModelClient, ModelResult
from backend.pipeline import ingest, ledger, packs
from backend.storage import models as m
from backend.storage.agent_repo import AgentStore
from backend.storage.repositories import WorkspaceContext

MAX_LEDGER_BATCHES = 3  # per run: the rest stay in the review queue (docs/01 FR-60 budget)
RECENT_DAYS = 120  # without an import id, look at recent low-confidence rows only
QUERY_LIMIT = 200
QUERY_VERSION = "txnq-1"


def _as_of(state: ForesightState) -> date:
    raw = state.get("as_of")
    return date.fromisoformat(raw) if raw else date.today()


# ------------------------------------------------------------------------------ ledger


def ledger_node(state: ForesightState, ctx: RunContext) -> NodeOutput:
    ws = ctx.store.ctx
    cpack = packs.categorisation_pack(ws.workspace.country)
    latest = ws.latest_categorisations()
    import_id = state.get("import_id")
    since = _as_of(state) - timedelta(days=RECENT_DAYS)
    rows = [
        r
        for r in ws.transactions()
        if (r.import_batch_id == import_id if import_id else r.posted_on >= since)
        and r.id in latest
    ]
    pending: list[tuple[m.Transaction, m.Categorisation]] = []
    held = 0
    for row in rows:
        cat = latest[row.id]
        txn, rule = ledger.transaction(row), ledger.categorisation(cat)
        if lg.is_candidate(txn, rule):
            if row.suspicious_text:
                held += 1  # never sent: stays with its rule answer, for review
                continue
            pending.append((row, cat))
    base = {"candidates": len(pending) + held, "suspicious_held_back": held}
    if not pending:
        return NodeOutput(output={**base, "sent": 0}, label="Categorising transactions")
    if ctx.model_client is None:
        return NodeOutput(
            output={**base, "sent": 0, "model": "not configured"},
            label="Categorising transactions (rules only)",
        )
    by_id = {row.id: (row, cat) for row, cat in pending}
    txns = {row.id: ledger.transaction(row) for row, _ in pending}
    result = lg.categorise_with_model(
        list(txns.values()),
        cpack,
        ctx.model_client,
        locale_pack=state.get("locale_pack") or "uk",
        max_batches=MAX_LEDGER_BATCHES,
        before_call=ctx.before_llm,
        after_call=ctx.charge,
    )
    applied = 0
    for txn_id, answer in result.results.items():
        row, cat = by_id[txn_id]
        final = lg.merge(ledger.categorisation(cat), answer)
        if final is answer:
            ws.add(ledger.categorisation_row(final, supersedes=cat.id))
            applied += 1
    learned = _teach_memory(ws, txns, result.results)
    if applied:
        ws.append_audit(
            "txn.categorised_by_model",
            "agent_run",
            ctx.run_id,
            actor="agent:ledger",
            after={"applied": applied, "learned": learned, "models": result.models},
            run_id=ctx.run_id,
        )
        ws.bump_data_version()
        ingest.detect(ws)
    ws.session.flush()
    return NodeOutput(
        output={
            **base,
            "sent": result.sent,
            "applied": applied,
            "learned": learned,
            "failed_batches": result.failed_batches,
            "invalid_items": result.invalid,
            "llm_call_rate": round(result.sent / len(rows), 4) if rows else 0.0,
        },
        llm=result.calls,
        prompt_version=result.prompt_version,
        status="retried" if result.failed_batches else "ok",
        label="Categorising transactions",
    )


def _teach_memory(
    ws: WorkspaceContext,
    txns: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> int:
    updates = lg.memory_updates(txns, answers)
    if not updates:
        return 0
    memory = ingest.merchant_memory(ws)
    known = ws.counterparties()
    taught = 0
    for cpty, category in sorted(updates.items()):
        new = learn(memory, cpty, category, "learned")
        if new.get(cpty) == memory.get(cpty):
            continue  # a user correction (or the same answer) is already there
        memory = new
        row = known.get(cpty)
        if row is None:
            continue
        row.default_category_key = category
        row.memory_source = "learned"
        taught += 1
    return taught


# ------------------------------------------------------------------------------ ledger_query

_MONTHS = {
    name: i
    for i, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}


def period_range(period: str | None, as_of: date) -> tuple[date | None, date | None]:
    """'last_30d' / 'last 30 days' / 'March' / 'this month' / 'last month' → a date range."""
    if not period:
        return None, None
    text = period.strip().lower()
    days = re.match(r"^last[_ ](\d{1,3})\s*(?:d|days?)$", text)
    if days:
        return as_of - timedelta(days=int(days.group(1)) - 1), as_of
    if text in {"this month", "this_month"}:
        return as_of.replace(day=1), as_of
    if text in {"last month", "last_month"}:
        end = as_of.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    month = _MONTHS.get(text)
    if month:
        year = as_of.year if month <= as_of.month else as_of.year - 1
        start = date(year, month, 1)
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        return start, min(nxt - timedelta(days=1), as_of)
    return None, None


def ledger_query_node(state: ForesightState, ctx: RunContext) -> NodeOutput:
    ws = ctx.store.ctx
    slots: Mapping[str, Any] = (state.get("intent") or {}).get("slots") or {}
    category = slots.get("category_key") or slots.get("category")
    merchant = slots.get("merchant")
    start, end = period_range(str(slots.get("period") or "") or None, _as_of(state))
    total, page = ws.transaction_page(
        date_from=start,
        date_to=end,
        category_key=str(category) if category and "." in str(category) else None,
        limit=QUERY_LIMIT,
    )
    if merchant:
        needle = str(merchant).upper()
        page = [(t, c) for t, c in page if needle in (t.counterparty or t.normalised).upper()]
        total = len(page)
    filters = {
        "workspace_id": ws.workspace_id,
        "category_key": category,
        "merchant": merchant,
        "from": start.isoformat() if start else None,
        "to": end.isoformat() if end else None,
        "data_version": int(ws.workspace.data_version or 0),
        "version": QUERY_VERSION,
    }
    result = {
        "transaction_ids": [t.id for t, _ in page],
        "count": total,
        "shown": len(page),
        "total_minor": sum(t.amount_minor for t, _ in page),
        "currency": ws.workspace.home_currency,
    }
    calc = record("txn_query", filters, filters, result, QUERY_VERSION)
    if ws.calculation(calc.id) is None:
        ws.add(
            m.Calculation(
                id=calc.id,
                kind="txn_query",
                inputs_hash=calc.inputs_hash,
                params=calc.params,
                result=calc.result,
                engine_version=QUERY_VERSION,
                data_version=filters["data_version"],
            )
        )
        ws.session.flush()
    return NodeOutput(
        update={"txn_queries": [calc.id]},
        output={"txn_query": calc.id, "count": total, "filters": filters},
        tool_calls=[{"name": "transaction_page", "result_ref": calc.id}],
        label="Finding the transactions",
    )


# ------------------------------------------------------------------------------ analyst


def stored_ranking(ws: WorkspaceContext) -> list[m.Finding]:
    """The live findings ranked for the workspace's current data version, most salient first
    (empty when nothing has been ranked since the data last changed)."""
    version = int(ws.workspace.data_version or 0)
    rows = [
        f
        for f in ws.all(m.Finding)
        if f.status == "open" and f.salience is not None and f.data_version == version
    ]
    return sorted(rows, key=lambda f: (-(f.salience or 0), -f.score, f.id))


def analyst_node(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """Findings, ranked once per data change (owner decision, 13 Oct 2026; docs/06 §6.1).

    A refresh (import, risk detection, the daily run) detects candidates and has the model rank
    and word them. A question reuses that stored ranking and never calls the model; when nothing
    is ranked for the current data (e.g. straight after seeding) it ranks deterministically."""
    ws = ctx.store.ctx
    question = state.get("workflow") == "conversation"
    if question:
        stored = stored_ranking(ws)
        if stored:
            ordered = [f.id for f in stored]
            return NodeOutput(
                update={"findings": ordered},
                output={"candidates": len(ordered), "ranked": ordered, "reused": True},
                cached=True,
                label="Using the latest spending analysis",
            )
    home = ws.workspace.home_currency
    rows = ws.transactions(currency=home)
    latest = ws.latest_categorisations()
    txns = [ledger.transaction(r) for r in rows]
    cats = [ledger.categorisation(latest[r.id]) for r in rows if r.id in latest]
    cpack = packs.categorisation_pack(ws.workspace.country)
    as_of = fd.data_end(txns, _as_of(state))
    holidays = packs.holidays(ws.workspace.country, (t.posted_on for t in txns))
    specs = fd.build_candidates(
        txns, cats, cpack, as_of=as_of, workspace_id=ws.workspace_id, currency=home,
        holidays=holidays,
    )  # fmt: skip
    persisted = fd.persist(ws, specs, run_id=ctx.run_id)
    pairs = [(row.id, spec) for row, spec in zip(persisted, specs, strict=True)]
    if not pairs:
        return NodeOutput(
            update={"findings": []},
            output={"candidates": 0},
            label="Analysing spending patterns",
        )
    calls: Sequence[ModelResult] = ()
    if question or ctx.model_client is None:
        ranking = an.template_ranking(pairs)
        label = (
            "Analysing spending patterns"
            if question
            else "Analysing spending patterns (no AI ranking)"
        )
    else:
        ranking = an.rank_with_model(
            pairs,
            ctx.model_client,
            locale_pack=state.get("locale_pack") or "uk",
            before_call=ctx.before_llm,
            after_call=ctx.charge,
        )
        calls = ranking.calls
        label = "Analysing spending patterns"
    rows_by_id = {row.id: row for row in persisted}
    for worded in ranking.ranked:
        row = rows_by_id[worded.finding_id]
        row.status = "open"
        row.salience = worded.salience
        row.headline = worded.headline
        row.detail = worded.explanation
        row.wording_source = worded.source
    for fid, reason in ranking.discarded.items():
        row = rows_by_id[fid]
        row.status = "discarded"
        row.discard_reason = reason[:500]
    ws.session.flush()
    ordered = [w.finding_id for w in ranking.ranked]
    return NodeOutput(
        update={"findings": ordered},
        output={
            "candidates": len(pairs),
            "ranked": ordered,
            "discarded": sorted(ranking.discarded),
            "wording": {w.finding_id: w.source for w in ranking.ranked},
            "violations": ranking.violations,
        },
        llm=calls,
        prompt_version=ranking.prompt_version or None,
        status="retried" if ranking.repaired else "ok",
        label=label,
    )


def nodes() -> dict[str, NodeSpec]:
    return {
        "ledger": NodeSpec("ledger", "ledger", "llm", ledger_node, "Categorising transactions"),
        "ledger_query": NodeSpec(
            "ledger_query", "ledger", "tool", ledger_query_node, "Finding the transactions"
        ),
        "analyst": NodeSpec(
            "analyst", "analyst", "llm", analyst_node, "Analysing spending patterns"
        ),
    }


# ------------------------------------------------------------------------------ ING-13


@dataclass
class TableProposal:
    table_index: int
    profile: FormatProfile | None
    problems: list[str] = field(default_factory=list)
    rows_parsed: int = 0


@dataclass
class FormatProposalRun:
    run_id: str | None
    proposals: list[TableProposal] = field(default_factory=list)

    @property
    def needed(self) -> bool:
        return self.run_id is not None


def tables_needing_columns(
    ws: WorkspaceContext, file_name: str, data: bytes
) -> list[tuple[int, Any]]:
    """(index, located table) for tables no saved/built-in profile or heuristic can read."""
    from backend.finance_core.importers.table_locator import decode, locate_tables

    saved = [ledger.profile(r.definition) for r in ws.all(m.FormatProfileRow)]
    fi = import_file(
        file_name,
        data,
        pack=packs.locale_pack(ws.workspace.country),
        home_currency=ws.workspace.home_currency,
        saved_profiles=saved,
    )
    pending = {
        i
        for i, t in enumerate(fi.tables)
        if any(q.kind == "columns" for q in blocking_questions(t.result))
    }
    if not pending:
        return []
    located = [t for t in locate_tables(decode(data)) if t.rows]
    return [(i, located[i]) for i in sorted(pending) if i < len(located)]


def propose_format_profiles(
    store: AgentStore,
    model_client: ModelClient,
    file_name: str,
    data: bytes,
) -> FormatProposalRun:
    """ING-13: one `propose_format_profile` step per unreadable table, inside an AgentRun, each
    proposal checked by parsing the file with it. Nothing is saved until the user confirms."""
    ws = store.ctx
    tables = tables_needing_columns(ws, file_name, data)
    if not tables:
        return FormatProposalRun(run_id=None)
    run = store.create_run(
        workflow="ingestion",
        trigger="user",
        data_version=int(ws.workspace.data_version or 0),
        prefs_version=0,
        deadline_at=deadline_for("ingestion"),
    )
    store.session.flush()
    ctx = RunContext(
        store=store,
        run_id=run.id,
        workflow="ingestion",
        deadline_at=run.deadline_at,
        model_client=model_client,
    )
    out = FormatProposalRun(run_id=run.id)
    locale = "in" if ws.workspace.country.upper() == "IN" else "uk"

    for index, table in tables:

        def step(
            state: ForesightState, rc: RunContext, table: Any = table, index: int = index
        ) -> NodeOutput:
            rc.before_llm()
            proposal = fp.propose(
                table.headers, [cells for _r, cells in table.rows], rc.require_model_client(),
                locale_pack=locale,
            )  # fmt: skip
            rc.charge(proposal.calls)
            checked = TableProposal(index, proposal.profile, list(proposal.problems))
            if proposal.profile is not None:
                checked.rows_parsed, more = _check_parse(ws, file_name, data, proposal.profile)
                checked.problems += more
                if more:
                    checked.profile = None
            out.proposals.append(checked)
            return NodeOutput(
                output={
                    "table_index": index,
                    "proposed": checked.profile is not None,
                    "problems": checked.problems,
                    "rows_parsed": checked.rows_parsed,
                    "withheld_headers": proposal.withheld_headers,
                    "confidence": proposal.confidence,
                },
                llm=proposal.calls,
                prompt_version=proposal.prompt_version,
                status="ok" if checked.profile is not None else "failed",
                label="Reading the columns of a new statement layout",
            )

        spec = NodeSpec(
            "propose_format_profile", "ledger", "llm", step, "Reading the statement's columns"
        )
        instrument(spec, ctx)({"run_id": run.id, "workflow": "ingestion"})
    store.finish_run(run.id, status="succeeded")
    store.session.flush()
    return out


def _check_parse(
    ws: WorkspaceContext, file_name: str, data: bytes, profile: FormatProfile
) -> tuple[int, list[str]]:
    fi = import_file(
        file_name,
        data,
        pack=packs.locale_pack(ws.workspace.country),
        home_currency=ws.workspace.home_currency,
        saved_profiles=[profile],
    )
    rows = sum(len(t.result.rows) for t in fi.tables)
    if any(q.kind == "columns" for t in fi.tables for q in t.result.questions):
        return rows, ["the importer still couldn't read the columns with this mapping"]
    failed = [t for t in fi.tables if t.result.reconciliation.status.value == "failed"]
    if failed:
        return rows, ["the file doesn't add up with this mapping"]
    return rows, []


def confirm_format_profile(
    ws: WorkspaceContext, profile: FormatProfile, *, actor: str = "user"
) -> m.FormatProfileRow:
    """H1: the user confirmed the proposed columns. Saved and reused with no model call."""
    final = fp.confirmed(profile)
    existing = ws.session.scalars(
        ws.select(m.FormatProfileRow).where(m.FormatProfileRow.profile_id == final.profile_id)
    ).first()
    if existing is not None:
        existing.source = "user_confirmed"
        existing.definition = ledger.profile_json(final)
        row = existing
    else:
        from backend.storage.ids import new_id

        row = m.FormatProfileRow(
            id=new_id("fmt"),
            profile_id=final.profile_id,
            label=final.label[:120],
            source="user_confirmed",
            definition=ledger.profile_json(final),
            confirmations=0,
        )
        ws.add(row)
    ws.append_audit(
        "format_profile.confirmed",
        "format_profile",
        final.profile_id,
        actor=actor,
        after={"columns": {k: list(v) for k, v in final.columns.items()}},
    )
    ws.session.flush()
    return row
