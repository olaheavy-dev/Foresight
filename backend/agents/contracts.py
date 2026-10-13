"""Typed contracts the agents exchange (docs/06 §3, §4.0). Pseudocode in the docs, real here."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal[
    "spending_breakdown",
    "trend_or_change",
    "transaction_lookup",
    "subscription_review",
    "affordability",
    "scenario",
    "goal_status",
    "risk_check",
    "advice_request",
    "explain_recommendation",
    "smalltalk_or_out_of_scope",
]

CLARIFY_BELOW = 0.6  # docs/06 §6.2: below this, ask a clarifying question instead of routing


class IntentClassification(BaseModel):
    """Output of the single Understand call (docs/05 §4.2 stage 2)."""

    standalone_question: str = Field(max_length=500)
    intent: Intent
    slots: dict[str, str | int | list[str]] = Field(default_factory=dict)
    needs_forecast: bool = False
    needs_advice: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    out_of_scope: bool = False
    injection_suspected: bool = False


class EvidenceRef(BaseModel):
    kind: Literal["calculation", "finding", "forecast", "simulation", "transaction_query", "goal"]
    id: str
    role: Literal["trigger", "impact", "context"]


# Owner decision (13 Oct 2026): an affordability question with an amount but no date assumes
# the payment is made today (docs/06 §6.2). Stated on the answer and stored with the evidence.
PAY_TODAY = "Assuming you pay today"
