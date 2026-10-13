"""Deterministic behaviour finding candidates (docs/06 §4.2, docs/07 §3.4 `Finding`).

The Behaviour Analyst never creates a finding: it ranks, words or discards the candidates built
here from the `finance_core` detectors. Each candidate carries:

- its statistics, stored once as a Calculation (`kind="finding_stats"`, content-addressed id);
- the placeholders a headline may use (`{{calc_…#path|format}}`, docs/08 §5.0), so every number
  shown is hydrated from that Calculation and a model never writes one (V-07);
- a templated headline and detail, used when no model is available or its wording fails checks;
- a reproducible transaction query for the supporting rows.

Persisted findings are keyed by `dedupe_key`: a refresh confirms an open finding (new statistics,
same id) rather than adding a duplicate, and one no longer detected is marked `resolved`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from backend.finance_core.calc import record
from backend.finance_core.categorise.pack import CategorisationPack
from backend.finance_core.detect.recurring import RecurringReport, detect_recurring
from backend.finance_core.detect.trends import CategoryTrend, category_trends
from backend.finance_core.types import Categorisation, Transaction
from backend.storage import models as m
from backend.storage.ids import new_id
from backend.storage.repositories import WorkspaceContext

FINDINGS_VERSION = "findings-1.0.0"
OPEN_STATUSES = ("candidate", "open")


def label_for(category_key: str) -> str:
    """'food.delivery' → 'food delivery' (category keys are stable labels, not numbers)."""
    return category_key.replace(".", " ").replace("_", " ")


@dataclass(frozen=True)
class CandidateSpec:
    kind: str
    dedupe_key: str
    subject: dict[str, Any]
    stats: dict[str, Any]
    strength: str  # strong | moderate | weak
    severity: str  # info | watch | act
    score: float  # deterministic salience score (higher = more salient)
    calc_id: str
    calc_params: dict[str, Any]
    placeholders: dict[str, str]  # name → "{{calc_…#path|format}}"
    headline: str
    detail: str
    txn_query: dict[str, Any] = field(default_factory=dict)


def _ph(calc_id: str, path: str, fmt: str) -> str:
    return "{{" + f"{calc_id}#{path}|{fmt}" + "}}"


def _spike(trend: CategoryTrend, workspace_id: str, currency: str) -> CandidateSpec:
    stats = {
        "category_key": trend.category_key,
        "recent_minor": trend.recent_minor,
        "usual_minor": trend.usual_minor,
        "change_share": round(trend.change_share, 4),
        "robust_z": round(min(trend.robust_z, 99.0), 3),
        "count": trend.count,
        "window_start": trend.window_start.isoformat(),
        "window_end": trend.window_end.isoformat(),
        "currency": currency,
    }
    params = {"workspace_id": workspace_id, "detector": "category_trend", "version": "trend-1"}
    calc = record("finding_stats", stats, params, stats, FINDINGS_VERSION)
    ph = {
        "recent": _ph(calc.id, "recent_minor", "money"),
        "usual": _ph(calc.id, "usual_minor", "money"),
        "change": _ph(calc.id, "change_share", "pct_change"),
        "count": _ph(calc.id, "count", "count"),
        "window_end": _ph(calc.id, "window_end", "date"),
    }
    label = label_for(trend.category_key)
    strong = trend.robust_z >= 3.0 and trend.change_share >= 0.25
    return CandidateSpec(
        kind="category_spike",
        dedupe_key=f"category_spike:{trend.category_key}",
        subject={"category_key": trend.category_key},
        stats=stats,
        strength="strong" if strong else "moderate",
        severity="watch" if trend.change_share >= 0.3 else "info",
        score=round(
            min(trend.change_share, 3.0) + (trend.recent_minor - trend.usual_minor) / 1e5, 6
        ),
        calc_id=calc.id,
        calc_params=calc.params,
        placeholders=ph,
        headline=f"Spending on {label} is up {ph['change']} on usual",
        detail=(
            f"{ph['recent']} in the month to {ph['window_end']} ({ph['count']} payments), "
            f"against a usual {ph['usual']}."
        ),
        txn_query={
            "category": trend.category_key,
            "from": trend.window_start.isoformat(),
            "to": trend.window_end.isoformat(),
        },
    )


def _price_changes(
    report: RecurringReport, labels: dict[str, str], workspace_id: str, currency: str
) -> list[CandidateSpec]:
    out = []
    for pc in report.price_changes:
        prev, latest = abs(pc.previous_minor), abs(pc.latest_minor)
        if prev == 0:
            continue
        stats = {
            "obligation_key": pc.obligation_key,
            "previous_minor": prev,
            "latest_minor": latest,
            "change_share": round((latest - prev) / prev, 4),
            "changed_on": pc.changed_on.isoformat(),
            "currency": currency,
        }
        params = {"workspace_id": workspace_id, "detector": "price_change", "version": "rec-1"}
        calc = record("finding_stats", stats, params, stats, FINDINGS_VERSION)
        ph = {
            "previous": _ph(calc.id, "previous_minor", "money"),
            "latest": _ph(calc.id, "latest_minor", "money"),
            "change": _ph(calc.id, "change_share", "pct_change"),
            "changed_on": _ph(calc.id, "changed_on", "date"),
        }
        label = labels.get(pc.obligation_key, "A regular payment")
        out.append(
            CandidateSpec(
                kind="price_change",
                dedupe_key=f"price_change:{pc.obligation_key}:{pc.changed_on.isoformat()}",
                subject={"obligation_key": pc.obligation_key, "label": label},
                stats=stats,
                strength="strong",
                severity="info",
                score=round(0.5 + abs((latest - prev) / prev), 6),
                calc_id=calc.id,
                calc_params=calc.params,
                placeholders=ph,
                headline=f"{label} changed to {ph['latest']}",
                detail=f"It was {ph['previous']} before {ph['changed_on']}.",
                txn_query={"obligation_key": pc.obligation_key},
            )
        )
    return out


def _overlaps(
    report: RecurringReport, labels: dict[str, str], workspace_id: str, currency: str
) -> list[CandidateSpec]:
    out = []
    for ov in report.overlaps:
        keys = sorted(ov.obligation_keys)
        stats = {
            "family": ov.family,
            "obligation_keys": keys,
            "services": len(keys),
            "monthly_total_minor": abs(ov.monthly_total_minor),
            "currency": currency,
        }
        params = {
            "workspace_id": workspace_id,
            "detector": "subscription_overlap",
            "version": "rec-1",
        }
        calc = record("finding_stats", stats, params, stats, FINDINGS_VERSION)
        ph = {
            "total": _ph(calc.id, "monthly_total_minor", "money"),
            "services": _ph(calc.id, "services", "count"),
        }
        names = ", ".join(labels.get(k, k) for k in keys)
        family = ov.family.replace("_", " ")
        out.append(
            CandidateSpec(
                kind="subscription_overlap",
                dedupe_key=f"subscription_overlap:{ov.family}:{'|'.join(keys)}",
                subject={"family": ov.family, "obligation_keys": keys, "labels": names},
                stats=stats,
                strength="strong",
                severity="info",
                score=round(0.4 + abs(ov.monthly_total_minor) / 1e5, 6),
                calc_id=calc.id,
                calc_params=calc.params,
                placeholders=ph,
                headline=f"You pay for {ph['services']} {family} services",
                detail=f"{names}: together about {ph['total']} a month.",
                txn_query={"obligation_keys": keys},
            )
        )
    return out


def build_candidates(
    txns: Sequence[Transaction],
    cats: Sequence[Categorisation],
    pack: CategorisationPack,
    *,
    as_of: date,
    workspace_id: str,
    currency: str,
    holidays: frozenset[date] = frozenset(),
) -> list[CandidateSpec]:
    """All candidates for one ledger, most salient first (deterministic)."""
    specs = [
        _spike(t, workspace_id, currency)
        for t in category_trends(txns, cats, as_of)
        if t.is_spike and t.recent_minor > t.usual_minor
    ]
    report = detect_recurring(txns, cats, pack, holidays)
    labels = {o.key: o.label for o in report.obligations}
    specs += _price_changes(report, labels, workspace_id, currency)
    specs += _overlaps(report, labels, workspace_id, currency)
    return sorted(specs, key=lambda s: (-s.score, s.dedupe_key))


def data_end(txns: Iterable[Transaction], today: date) -> date:
    """Windows end at the last day with data (never in the future)."""
    last = max((t.posted_on for t in txns), default=today)
    return min(last, today)


def persist(
    ctx: WorkspaceContext, specs: Sequence[CandidateSpec], *, run_id: str | None = None
) -> list[m.Finding]:
    """Upsert candidates by dedupe key; resolve open findings no longer detected."""
    now = datetime.now(timezone.utc)
    existing = {f.dedupe_key: f for f in ctx.all(m.Finding)}
    seen: set[str] = set()
    rows: list[m.Finding] = []
    for spec in specs:
        if ctx.calculation(spec.calc_id) is None:
            ctx.add(
                m.Calculation(
                    id=spec.calc_id,
                    kind="finding_stats",
                    inputs_hash=record(
                        "finding_stats", spec.stats, spec.calc_params, spec.stats, FINDINGS_VERSION
                    ).inputs_hash,
                    params=spec.calc_params,
                    result=spec.stats,
                    engine_version=FINDINGS_VERSION,
                    data_version=ctx.workspace.data_version,
                )
            )
        row = existing.get(spec.dedupe_key)
        if row is None or row.status not in (*OPEN_STATUSES, "resolved"):
            if row is not None:
                # dismissed/acknowledged findings stay as the user left them
                seen.add(spec.dedupe_key)
                continue
            row = m.Finding(id=new_id("fnd"), dedupe_key=spec.dedupe_key, first_detected_at=now)
            ctx.add(row)
        row.kind = spec.kind
        row.subject = spec.subject
        row.stats = spec.stats
        row.strength = spec.strength
        row.severity = spec.severity
        row.score = spec.score
        row.calc_ids = [spec.calc_id]
        row.txn_query = spec.txn_query
        row.status = "candidate"
        row.discard_reason = None
        row.headline = spec.headline
        row.detail = spec.detail
        row.wording_source = "template"
        row.data_version = int(ctx.workspace.data_version or 0)
        row.run_id = run_id
        row.last_confirmed_at = now
        seen.add(spec.dedupe_key)
        rows.append(row)
    for key, row in existing.items():
        if key not in seen and row.status in OPEN_STATUSES:
            row.status = "resolved"
    ctx.session.flush()
    return rows
