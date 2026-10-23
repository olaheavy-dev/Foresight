"""The Forecaster agent (docs/06 §4.3, W3): what-if text → ScenarioSpec → simulate → drivers.

The model only parses: it returns a typed `ScenarioSpec` or asks for clarification, never a number
of its own. Simple what-ifs go to the `fast` tier; questions with several changes go to
`reasoning` (docs/06 §13). The simulation runs on the same engine and seed as the baseline, and the
driver text is a template filled from the result (value placeholders only).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.agents.cache import prompt_version
from backend.agents.prompting import system_prompt
from backend.finance_core.types import ScenarioModifier, ScenarioSpec
from backend.llm.client import ModelClient, ModelResult, ModelTier

PARSE_PROMPT = "forecaster_parse"

ModifierType = Literal[
    "one_off_outflow",
    "one_off_inflow",
    "split_outflow",
    "income_delay",
    "income_change_pct",
    "recurring_add",
    "recurring_change",
    "recurring_cancel",
    "category_cut_pct",
    "category_cap",
    "buffer_override",
]


class ModifierModel(BaseModel):
    """docs/07 §6.5 field names (what the model and the eval gold use)."""

    model_config = ConfigDict(extra="forbid")

    type: ModifierType
    date: str | None = None
    start_date: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    amount_minor: int | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, max_length=60)
    category_key: str | None = None
    income_stream_id: str | None = None
    recurring_id: str | None = None
    days: int | None = None
    occurrences: int | None = None
    pct: int | None = Field(default=None, ge=-100, le=300)
    cadence: Literal["weekly", "fortnightly", "monthly"] | None = None
    instalments: int | None = Field(default=None, ge=1, le=36)
    monthly_cap_minor: int | None = Field(default=None, ge=0)
    buffer_minor: int | None = Field(default=None, ge=0)


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: Literal["scenario_spec/1"] = Field(default="scenario_spec/1", alias="schema")
    name: str = Field(max_length=60)
    currency: str = Field(min_length=3, max_length=3)
    scope: Literal["mine", "household", "account"] = "mine"
    modifiers: list[ModifierModel] = Field(max_length=12)
    assumptions: list[str] = Field(default_factory=list)


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(max_length=200)
    slot: str = Field(max_length=40)  # the missing value, e.g. "amount", "category", "days"
    options: list[str] = Field(default_factory=list, max_length=4)


class ScenarioParse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["parsed", "needs_clarification"]
    spec: SpecModel | None = None
    clarification: Clarification | None = None


@dataclass
class ParseOutcome:
    parse: ScenarioParse
    tier: ModelTier
    llm: list[ModelResult] = field(default_factory=list)
    prompt_version: str = ""


_CUES = re.compile(
    r"(?i)[£$€]\s?\d|\d+\s?%|\bcancel|\bcut\b|\bcap\b|\blate\b|\blose\b|\bdrop\b|\brise\b|"
    r"\bincrease|\bdecrease|\bgoes up\b|\bgoes down\b|\bdelay"
)


def tier_for(question: str) -> ModelTier:
    """Several changes in one question → reasoning tier; a single change → fast."""
    return ModelTier.REASONING if len(_CUES.findall(question)) >= 2 else ModelTier.FAST


def parse_messages(
    question: str,
    *,
    today: date,
    currency: str,
    categories: Sequence[str],
    recurring: Sequence[dict[str, str]],
    income: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    data = {
        "question": question,
        "today": today.isoformat(),
        "weekday": today.strftime("%A"),
        "currency": currency,
        "categories": list(categories),
        "recurring": list(recurring),
        "income": list(income),
    }
    return [
        {"role": "system", "content": system_prompt(PARSE_PROMPT)},
        {"role": "user", "content": json.dumps({"data": data}, ensure_ascii=False)},
    ]


def parse_scenario(
    question: str,
    model_client: ModelClient,
    *,
    today: date,
    currency: str,
    categories: Sequence[str],
    recurring: Sequence[dict[str, str]],
    income: Sequence[dict[str, str]],
    locale_pack: str = "uk",
    before_llm: Callable[[], None] | None = None,
) -> ParseOutcome:
    tier = tier_for(question)
    if before_llm is not None:
        before_llm()
    result = model_client.structured(
        tier=tier,
        messages=parse_messages(
            question,
            today=today,
            currency=currency,
            categories=categories,
            recurring=recurring,
            income=income,
        ),
        output=ScenarioParse,
        name="scenario_parse",
        max_tokens=900,
        locale_pack=locale_pack,
    )
    return ParseOutcome(result.value, tier, list(result.calls), prompt_version(PARSE_PROMPT))


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def to_engine_spec(spec: SpecModel) -> ScenarioSpec:
    """The parsed spec as the engine's ScenarioSpec (docs/07 §6.5 → finance_core field names)."""
    mods: list[ScenarioModifier] = []
    for m in spec.modifiers:
        when = _d(m.date)
        start = _d(m.start_date)
        mods.append(
            ScenarioModifier(
                type=m.type,
                date=when if m.type != "split_outflow" else (start or when),
                amount_minor=m.amount_minor,
                label=m.label or "",
                category_key=m.category_key,
                income_stream_key=m.income_stream_id,
                days=m.days,
                occurrences=m.occurrences,
                recurring_id=m.recurring_id,
                from_date=_d(m.from_date) or (start if m.type == "recurring_add" else None),
                to_date=_d(m.to_date),
                pct=m.pct,
                cadence=m.cadence,
                instalments=m.instalments,
                monthly_cap_minor=m.monthly_cap_minor,
                buffer_minor=m.buffer_minor,
            )
        )
    return ScenarioSpec(name=spec.name, currency=spec.currency, modifiers=tuple(mods))


def drivers(delta_lows: Sequence[tuple[date, int, int]]) -> list[dict[str, Any]]:
    """Template driver lines, one per pay cycle whose low moved (placeholders only)."""
    out = []
    for payday, before, after in delta_lows:
        if before == after:
            continue
        out.append(
            {
                "payday": payday.isoformat(),
                "text": "The lowest balance before {{payday}} moves from {{before}} to {{after}}.",
                "values": {"payday": payday.isoformat(), "before": before, "after": after},
            }
        )
    return out
