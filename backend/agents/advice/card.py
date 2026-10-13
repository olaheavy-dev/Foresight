"""The hydrated InterventionCard stored with an approved recommendation (docs/08 §5.7).

Built deterministically when the Verifier approves: the title and rationale have their
`{{placeholders}}` filled from the proposal's own parameters and the recomputed impact (server
formatting), and every figure on the card comes from `recompute_impact`, never from model text.
The composer shows the card as stored (`recommendation.proposal["card"]`); if it can't be built
the composer drops it rather than inventing one.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from backend.agents.advice.impact import Impact
from backend.agents.advice.models import InterventionProposal, Verification
from backend.app import views
from backend.app.ui_contracts.blocks import InterventionCard
from backend.app.ui_contracts.money import money_value
from backend.app.ui_contracts.primitives import MoneyAmount, PercentValue

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def _date(value: Any) -> str | None:
    try:
        d = value if isinstance(value, date) else date.fromisoformat(str(value))
    except ValueError:
        return None
    return f"{d.day} {d.strftime('%b')}"


def fill(text: str, p: InterventionProposal, impact: Impact, locale: str) -> str:
    """Replace placeholders with server-formatted values; an unknown one is dropped."""

    def money(minor: Any) -> str | None:
        if not isinstance(minor, int) or isinstance(minor, bool):
            return None
        return money_value(MoneyAmount(amount_minor=minor, currency=p.currency), locale,
                           "exact").display  # fmt: skip

    values = {
        "cap": money(p.params.get("monthly_cap_minor")),
        "amount": money(p.params.get("amount_minor")),
        "saving": money(impact.monthly_minor),
        "from_date": _date(p.params.get("from_date")),
        "to_date": _date(p.params.get("to_date")),
    }
    out = _PLACEHOLDER.sub(lambda m: values.get(m.group(1)) or "", text)
    return " ".join(out.split())


def _percent(share: float | None) -> PercentValue:
    value = min(1.0, max(0.0, share or 0.0))
    return PercentValue(kind="percent", value=value, display=f"{round(value * 100)}%")


def build_card(
    p: InterventionProposal,
    impact: Impact,
    verification: Verification,
    *,
    recommendation_id: str,
    verification_id: str,
    revisions: int,
    locale: str,
    forecast_calc_id: str | None,
) -> dict[str, Any] | None:
    """The card as a JSON-safe dict, or None when it can't be built faithfully."""
    if not impact.before or not impact.after:
        return None
    checks = [*verification.deterministic, *(verification.judge or [])]
    title = fill(p.title, p, impact, locale)
    monthly = impact.monthly_minor
    lows = [
        {
            "cycle_label": f"Before {_date(b.payday)}",
            "before": money_value(MoneyAmount(amount_minor=b.low_p50, currency=p.currency),
                                  locale, "rounded"),
            "after": money_value(MoneyAmount(amount_minor=a.low_p50, currency=p.currency),
                                 locale, "rounded"),
        }
        for b, a in zip(impact.before, impact.after, strict=False)
    ]  # fmt: skip
    triggered = [
        ref.id for ref in p.trigger_refs if ref.kind == "finding" and ref.id.startswith("fnd_")
    ]
    if forecast_calc_id:
        triggered.append(views.content_id("fc", forecast_calc_id))
    card = {
        "type": "InterventionCard",
        "block_id": "b-card",
        "placement": {"area": "tab", "tab": "recommendation"},
        "recommendation_id": recommendation_id,
        "version_id": f"{recommendation_id}-v{revisions + 1}",
        "title": title[:80] or p.action.replace("_", " "),
        "rationale_segments": [{"kind": "text", "text": fill(p.rationale, p, impact, locale)}],
        "actions": [{"type": p.action, "label": title[:80] or p.action, "detail": ""}],
        "impact": {
            "monthly_saving": (
                money_value(MoneyAmount(amount_minor=monthly, currency=p.currency), locale,
                            "exact") if monthly else None
            ),
            "p_breach_before": _percent(impact.risk_before),
            "p_breach_after": _percent(impact.risk_after),
            "p_breach_window": {"from": impact.before[0].payday.isoformat(),
                                "to": impact.before[-1].payday.isoformat()},
            "low_deltas": lows,
        },
        "verification": {
            "verdict": "approved",
            "revisions": revisions,
            "checks_passed": sum(1 for r in checks if r.passed),
            "checks_total": len(checks),
            "verification_id": verification_id,
        },
        "triggered_by": triggered,
        "status": "approved",
    }  # fmt: skip
    try:
        validated = InterventionCard.model_validate(card)
    except ValueError:
        return None
    dumped: dict[str, Any] = validated.model_dump(mode="json", by_alias=True)
    return dumped
