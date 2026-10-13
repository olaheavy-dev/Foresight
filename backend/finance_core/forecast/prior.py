"""Population prior for irregular household expenses (docs/07 §6.2b).

A short bank history may not yet show the lumpy purchases every household meets sooner or later
(furniture, appliances, repairs, holidays). The forecast blends the user's own one-off expenses
with a prior taken from national household-spending statistics, the way a Bayesian posterior mean
blends data with a prior:

    expected one-off cost per day = (1 − w) · observed rate + w · r · prior rate,
    w = strength / (days of history + strength)

so the prior matters most for a new user and fades as their own history grows. `r` scales the
average household to this user: their everyday spending per day divided by the survey's
comparable spending per day (total expenditure less housing, other non-consumption items and the
irregular categories themselves), clamped to `scale_bounds`.

The prior's values are pack data (e.g. locale_packs/uk_irregular_expenses.yaml, from the ONS
Living Costs and Food Survey), parsed here from the YAML text the application supplies; nothing
in this module reads files.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import yaml

DAYS_PER_WEEK = 7


@dataclass(frozen=True)
class IrregularPrior:
    currency: str
    source: str
    irregular_daily_minor: Fraction  # average household, all irregular categories
    comparison_daily_minor: Fraction  # the survey's comparable everyday spending per day
    event_interval_days: int  # mean days between lumps
    strength_days: int  # the prior counts as this many days of the user's own history
    scale_bounds: tuple[Fraction, Fraction]


def load_irregular_prior(yaml_text: str) -> IrregularPrior:
    data: dict[str, Any] = yaml.safe_load(yaml_text) or {}
    irregular = sum(int(v) for v in (data.get("irregular_weekly_minor") or {}).values())
    excluded_items = data.get("excluded_from_comparison_weekly_minor") or {}
    excluded = sum(int(v) for v in excluded_items.values())
    total = int(data["total_weekly_expenditure_minor"])
    comparison = total - excluded - irregular
    if irregular <= 0 or comparison <= 0:
        raise ValueError("irregular-expense prior needs positive irregular and comparison spend")
    lo, hi = (Fraction(str(b)) for b in data.get("scale_bounds", [0.5, 1.5]))
    return IrregularPrior(
        currency=str(data["currency"]),
        source=str(data.get("source", "")),
        irregular_daily_minor=Fraction(irregular, DAYS_PER_WEEK),
        comparison_daily_minor=Fraction(comparison, DAYS_PER_WEEK),
        event_interval_days=int(data.get("event_interval_days", 30)),
        strength_days=int(data.get("strength_days", 90)),
        scale_bounds=(lo, hi),
    )


def prior_weight(prior: IrregularPrior, history_days: int) -> Fraction:
    """w = strength / (history days + strength)."""
    return Fraction(prior.strength_days, max(0, history_days) + prior.strength_days)


def household_scale(prior: IrregularPrior, everyday_daily_minor: Fraction) -> Fraction:
    """This user's everyday spending relative to the survey's comparable spending, clamped."""
    lo, hi = prior.scale_bounds
    if everyday_daily_minor <= 0:
        return lo
    return min(max(everyday_daily_minor / prior.comparison_daily_minor, lo), hi)


def to_jsonable(prior: IrregularPrior) -> dict[str, object]:
    """A stable, JSON-ready description (hashed into the forecast's inputs hash)."""
    return {
        "currency": prior.currency,
        "source": prior.source,
        "irregular_daily_minor": str(prior.irregular_daily_minor),
        "comparison_daily_minor": str(prior.comparison_daily_minor),
        "event_interval_days": prior.event_interval_days,
        "strength_days": prior.strength_days,
        "scale_bounds": [str(b) for b in prior.scale_bounds],
    }
