"""The subset of a locale pack that categorisation and detection need.

The pack is data (e.g. locale_packs/uk.yaml). This module parses the YAML *text* it is given — it
never opens files — into typed, pre-compiled structures. Engine code must take every
locale-specific token (payment codes, merchants, payer patterns) from here, never hard-code them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

from backend.finance_core.types import Channel, FlowKind


@dataclass(frozen=True)
class ChannelMatcher:
    channel: Channel
    bank_types: frozenset[str]
    codes: frozenset[str]


@dataclass(frozen=True)
class Rule:
    category: str
    flow_kind: FlowKind
    direction: str  # "out" | "in" | "any"
    merchants: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class PayerPattern:
    pattern: re.Pattern[str]
    category: str


@dataclass(frozen=True)
class CategoryInfo:
    key: str
    nature: str
    default_flow_kind: FlowKind


@dataclass(frozen=True)
class CategorisationPack:
    pack_id: str
    country: str
    currency: str
    holiday_country: str
    holiday_subdiv: str | None
    payday_shift: str  # "previous_working_day" | "next_working_day"
    debit_shift: str
    one_off_multiple: float
    channels: tuple[ChannelMatcher, ...]
    noise_tokens: frozenset[str]
    payroll_markers: frozenset[str]
    government_payers: tuple[PayerPattern, ...]
    refund_markers: tuple[str, ...]
    card_bill_markers: tuple[str, ...]
    self_transfer_markers: tuple[str, ...]
    savings_markers: tuple[str, ...]
    subscription_families: dict[str, tuple[str, ...]]
    categories: dict[str, CategoryInfo]
    rules: tuple[Rule, ...]
    bank_category_priors: dict[str, dict[str, str]]
    protected_categories: frozenset[str]
    seasonal_defaults: dict[str, frozenset[int]]

    def default_flow_kind(self, category_key: str) -> FlowKind:
        info = self.categories.get(category_key)
        return info.default_flow_kind if info else FlowKind.SPENDING


def _strs(value: Any) -> tuple[str, ...]:
    return tuple(str(v).upper() for v in (value or ()))


def load_pack(yaml_text: str) -> CategorisationPack:
    data: dict[str, Any] = yaml.safe_load(yaml_text) or {}
    categories = {
        str(c["key"]): CategoryInfo(
            key=str(c["key"]),
            nature=str(c["nature"]),
            default_flow_kind=FlowKind(str(c["default_flow_kind"])),
        )
        for c in data.get("categories") or ()
    }
    rules = []
    for r in data.get("rules") or ():
        category = str(r["category"])
        flow = r.get("flow_kind")
        default = categories[category].default_flow_kind if category in categories else None
        rules.append(
            Rule(
                category=category,
                flow_kind=FlowKind(str(flow)) if flow else (default or FlowKind.SPENDING),
                direction=str(r.get("direction", "any")),
                merchants=_strs(r.get("merchants")),
                patterns=tuple(re.compile(str(p)) for p in r.get("patterns") or ()),
            )
        )
    holidays = data.get("holidays") or {}
    payday = data.get("payday") or {}
    return CategorisationPack(
        pack_id=str(data.get("id", "")),
        country=str(data.get("country", "")),
        currency=str(data.get("currency", "")),
        holiday_country=str(holidays.get("country", "")),
        holiday_subdiv=str(holidays["subdiv"]) if holidays.get("subdiv") else None,
        payday_shift=str(payday.get("weekend_shift", "previous_working_day")),
        debit_shift=str((data.get("debit_posting") or {}).get("weekend_shift", "next_working_day")),
        one_off_multiple=float(payday.get("one_off_multiple", 1.5)),
        channels=tuple(
            ChannelMatcher(
                channel=Channel(str(c["channel"])),
                bank_types=frozenset(str(t).upper() for t in c.get("bank_types") or ()),
                codes=frozenset(_strs(c.get("codes"))),
            )
            for c in data.get("channels") or ()
        ),
        noise_tokens=frozenset(_strs(data.get("noise_tokens"))),
        payroll_markers=frozenset(_strs(data.get("payroll_markers"))),
        government_payers=tuple(
            PayerPattern(pattern=re.compile(str(g["pattern"])), category=str(g["category"]))
            for g in data.get("government_payers") or ()
        ),
        refund_markers=_strs(data.get("refund_markers")),
        card_bill_markers=_strs(data.get("card_bill_markers")),
        self_transfer_markers=_strs(data.get("self_transfer_markers")),
        savings_markers=_strs(data.get("savings_markers")),
        subscription_families={
            str(k): _strs(v) for k, v in (data.get("subscription_families") or {}).items()
        },
        categories=categories,
        rules=tuple(rules),
        bank_category_priors={
            str(bank): {str(k).lower(): str(v) for k, v in (mapping or {}).items()}
            for bank, mapping in (data.get("bank_category_priors") or {}).items()
        },
        protected_categories=frozenset(str(c) for c in data.get("protected_categories") or ()),
        seasonal_defaults={
            str(k): frozenset(int(m) for m in v)
            for k, v in (data.get("seasonal_defaults") or {}).items()
        },
    )


def contains_phrase(normalised: str, phrase: str) -> bool:
    """Whole-word (or whole-phrase) match on an uppercase normalised narration."""
    if not phrase:
        return False
    return re.search(r"(?<![A-Z0-9])" + re.escape(phrase) + r"(?![A-Z0-9])", normalised) is not None
