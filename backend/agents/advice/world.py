"""What the Advisor and Verifier know about one profile at one point in time (docs/06 §4.4–4.5).

`AdviceWorld` is assembled from stored data by the graph (`world_from_store`) or from a persona's
truth files by the evals (`evals/suites/verifier.py`). The Verifier's deterministic rules read
only this object, so the same rules run in both places.

Spend windows follow the authored-set conventions (evals/datasets/authored/README.md): "last 30
days" ends on `as_of`; the "3-month median" (V-04) is the median of the three consecutive 30-day
windows ending on `as_of` (the last 30 days and the two before).
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from backend.agents.contracts import EvidenceRef
from backend.finance_core.calendar import obligation_dates
from backend.finance_core.types import Cadence, ForecastInputs, RecurringObligation

WINDOW_DAYS = 30
FORECAST_SUMMARY = (
    "Baseline cash-flow forecast for the coming pay cycles, including the lowest balance before "
    "each payday and the chance of going below the buffer."
)
TRAILING_DAYS = 90  # V-03: a target must appear in the trailing 90 days
MONTHLY_FACTOR = {
    Cadence.MONTHLY: 1.0,
    Cadence.WEEKLY: 52 / 12,
    Cadence.FOUR_WEEKLY: 13 / 12,
    Cadence.QUARTERLY: 1 / 3,
    Cadence.ANNUAL: 1 / 12,
}


@dataclass(frozen=True)
class SpendRow:
    on: date
    amount_minor: int  # signed: outflows < 0
    category: str
    flow_kind: str
    recurring_key: str | None = None


@dataclass(frozen=True)
class Finding:
    id: str
    finding_type: str
    subject: str
    summary: str = ""
    superseded: bool = False


@dataclass(frozen=True)
class Goal:
    id: str
    label: str
    target_minor: int
    target_date: date | None
    funded_by: str | None = None  # recurring obligation that pays into it


@dataclass(frozen=True)
class AdviceWorld:
    as_of: date
    currency: str
    locale_pack: str
    rows: tuple[SpendRow, ...]
    obligations: Mapping[str, RecurringObligation]
    findings: Mapping[str, Finding]
    forecast_ids: frozenset[str]
    protected_categories: frozenset[str]
    buffer_minor: int | None = None
    goals: Mapping[str, Goal] = field(default_factory=dict)
    account_currencies: Mapping[str, str] = field(default_factory=dict)
    betting_opt_in: bool = False
    user_requested_category: str | None = None
    active_recommendations: tuple[tuple[str, str], ...] = ()  # (action, target)
    joint: bool = False
    forecast_inputs: ForecastInputs | None = None
    # maps a world obligation key to the key the forecast inputs use (they can differ when the
    # world comes from truth labels and the forecast from detection)
    forecast_obligation_keys: Mapping[str, str] = field(default_factory=dict)
    pending_scenario: tuple[Any, ...] = ()  # ScenarioModifiers the question already assumes
    extra: Mapping[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- spend windows

    def category_spend(self, category: str, start: date, end: date) -> int:
        """Total outflow (≥ 0, minor units) in `category` on days in [start, end]."""
        return -sum(
            r.amount_minor
            for r in self.rows
            if r.category == category and start <= r.on <= end and r.amount_minor < 0
        )

    def window(self, back: int) -> tuple[date, date]:
        end = self.as_of - timedelta(days=WINDOW_DAYS * back)
        return end - timedelta(days=WINDOW_DAYS - 1), end

    def last_30d(self, category: str) -> int:
        return self.category_spend(category, *self.window(0))

    def median_3x30(self, category: str) -> int:
        totals = [self.category_spend(category, *self.window(k)) for k in (0, 1, 2)]
        return int(statistics.median(totals))

    def seen_recently(self, category: str) -> bool:
        start = self.as_of - timedelta(days=TRAILING_DAYS - 1)
        return any(r.category == category and start <= r.on <= self.as_of for r in self.rows)

    # ---------------------------------------------------------------- obligations

    def obligation(self, key: str | None) -> RecurringObligation | None:
        return self.obligations.get(key) if key else None

    def obligation_active(self, key: str | None) -> bool:
        ob = self.obligation(key)
        if ob is None:
            return False
        start = self.as_of - timedelta(days=TRAILING_DAYS - 1)
        if any(r.recurring_key == key and start <= r.on <= self.as_of for r in self.rows):
            return True
        return bool(obligation_dates(ob, start, self.as_of))

    def monthly_amount(self, key: str) -> int:
        ob = self.obligations[key]
        return round(abs(ob.amount_minor) * MONTHLY_FACTOR.get(ob.cadence, 1.0))

    def occurrences(self, key: str, start: date, end: date) -> list[date]:
        ob = self.obligation(key)
        holidays = self.forecast_inputs.holidays if self.forecast_inputs else frozenset()
        return obligation_dates(ob, start, end, holidays) if ob else []

    # ---------------------------------------------------------------- evidence

    def resolve(self, ref: EvidenceRef) -> bool:
        """Does the cited evidence exist in this profile, current (not superseded)?"""
        if ref.kind == "finding":
            f = self.findings.get(ref.id)
            return f is not None and not f.superseded
        if ref.kind in ("forecast", "simulation", "calculation"):
            return ref.id in self.forecast_ids
        if ref.kind == "goal":
            return ref.id in self.goals
        return False

    def evidence_summaries(self, refs: Sequence[EvidenceRef]) -> list[dict[str, Any]]:
        """Short, number-free summaries of cited evidence for the LLM judge (docs/05 §7.3)."""
        out: list[dict[str, Any]] = []
        for ref in refs:
            if ref.kind == "finding" and ref.id in self.findings:
                f = self.findings[ref.id]
                out.append(
                    {
                        "id": ref.id,
                        "kind": "finding",
                        "type": f.finding_type,
                        "about": f.subject,
                        "summary": f.summary,
                    }
                )
            elif ref.kind == "forecast" and ref.id in self.forecast_ids:
                out.append(
                    {
                        "id": ref.id,
                        "kind": "forecast",
                        "summary": FORECAST_SUMMARY,
                    }
                )
            elif ref.kind == "goal" and ref.id in self.goals:
                g = self.goals[ref.id]
                out.append({"id": ref.id, "kind": "goal", "label": g.label})
            else:
                out.append({"id": ref.id, "kind": ref.kind, "summary": "not found"})
        return out
