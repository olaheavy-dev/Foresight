"""Load the versioned rule pack (`rules.yaml`). Its sha256 is the rule-pack version."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

RULES_PATH = Path(__file__).with_name("rules.yaml")

Severity = Literal["block", "suspicious"]
Channel = Literal["chat", "data"]


@dataclass(frozen=True)
class Rule:
    id: str
    severity: Severity
    reason: str
    applies_to: frozenset[str]
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class RulePack:
    version: str
    sha256: str
    limits: dict[str, int]
    rules: tuple[Rule, ...]
    url_allow_list: frozenset[str]
    product_advice: dict[str, tuple[str, ...]]

    def for_channel(self, channel: Channel) -> tuple[Rule, ...]:
        return tuple(r for r in self.rules if channel in r.applies_to)

    @property
    def tag(self) -> str:
        """Short id for logs and `prompt_bundle_version`, e.g. guard-1.0.0+3f2a9c1d."""
        return f"{self.version}+{self.sha256[:8]}"


def parse_rule_pack(text: str) -> RulePack:
    data: dict[str, Any] = yaml.safe_load(text) or {}
    rules = []
    seen: set[str] = set()
    for raw in data.get("rules") or []:
        rid = str(raw["id"])
        if rid in seen:
            raise ValueError(f"duplicate rule id {rid}")
        seen.add(rid)
        severity = str(raw["severity"])
        if severity not in ("block", "suspicious"):
            raise ValueError(f"{rid}: severity must be block or suspicious")
        applies = frozenset(str(a) for a in raw.get("applies_to") or ())
        if not applies or not applies <= {"chat", "data"}:
            raise ValueError(f"{rid}: applies_to must be chat and/or data")
        rules.append(
            Rule(
                id=rid,
                severity=severity,  # type: ignore[arg-type]
                reason=str(raw.get("reason", "injection")),
                applies_to=applies,
                pattern=re.compile(str(raw["pattern"]), re.IGNORECASE),
            )
        )
    return RulePack(
        version=str(data["version"]),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        limits={str(k): int(v) for k, v in (data.get("limits") or {}).items()},
        rules=tuple(rules),
        url_allow_list=frozenset(str(h).lower() for h in data.get("url_allow_list") or ()),
        product_advice={
            str(pack): tuple(str(p).lower() for p in phrases)
            for pack, phrases in (data.get("product_advice") or {}).items()
        },
    )


@lru_cache(maxsize=1)
def load_rule_pack() -> RulePack:
    return parse_rule_pack(RULES_PATH.read_text(encoding="utf-8"))
