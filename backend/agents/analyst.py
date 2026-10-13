"""Behaviour Analyst (docs/06 §4.2, docs/10 AGT-04): ranks and words deterministic findings.

One reasoning-tier call per refresh. The model sees the candidates' statistics and their allowed
placeholders; it may rank, word or discard them, never create one. Its text is checked before it
is stored (docs/05 §7.4a L4, V-07):

- finding ids are an enum of the candidates given;
- every `{{…}}` placeholder must be one of that finding's own placeholders;
- no numerals, currency symbols or percentages outside placeholders, no links outside the
  allow-list, no product-advice phrases (`output_screen`).

Wording that fails gets one repair round; whatever still fails falls back to the finding's
template wording (`wording_source="template"`). With no model available the deterministic score
ranks the findings and the templates are used throughout.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from backend.agents.cache import PROMPTS_DIR, prompt_version
from backend.agents.findings import CandidateSpec
from backend.agents.guard import output_screen
from backend.mesh.mesh_client import MeshClient, MeshResult, ModelTier

PROMPT = "analyst_rank"
HEADLINE_MAX = 90
EXPLANATION_MAX = 240
_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def output_model(finding_ids: Sequence[str]) -> type[BaseModel]:
    id_type: Any = Literal[tuple(finding_ids)]
    ranked = create_model(
        "RankedFinding",
        __config__=ConfigDict(extra="forbid"),
        finding_id=(id_type, ...),
        salience=(int, Field(ge=1, le=5)),
        headline=(str, Field(max_length=HEADLINE_MAX)),
        explanation=(str, Field(max_length=EXPLANATION_MAX)),
    )
    discarded = create_model(
        "DiscardedFinding",
        __config__=ConfigDict(extra="forbid"),
        finding_id=(id_type, ...),
        reason=(str, Field(max_length=160)),
    )
    return create_model(
        "AnalystOutput",
        __config__=ConfigDict(extra="forbid"),
        findings=(list[ranked], ...),  # type: ignore[valid-type]
        discarded=(list[discarded], []),  # type: ignore[valid-type]
    )


@dataclass(frozen=True)
class Worded:
    finding_id: str
    salience: int
    headline: str
    explanation: str
    source: str  # llm | template


@dataclass
class AnalystResult:
    ranked: list[Worded] = field(default_factory=list)
    discarded: dict[str, str] = field(default_factory=dict)  # id → reason
    calls: list[MeshResult] = field(default_factory=list)
    violations: dict[str, list[str]] = field(default_factory=dict)  # id → problems found
    repaired: bool = False
    prompt_version: str = ""


def deterministic_salience(spec: CandidateSpec) -> int:
    base = {"watch": 4, "act": 5}.get(spec.severity, 2)
    return min(5, base + (1 if spec.strength == "strong" and spec.severity != "info" else 0))


def template_ranking(specs: Sequence[tuple[str, CandidateSpec]]) -> AnalystResult:
    ordered = sorted(specs, key=lambda p: (-deterministic_salience(p[1]), -p[1].score, p[0]))
    return AnalystResult(
        ranked=[
            Worded(fid, deterministic_salience(s), s.headline, s.detail, "template")
            for fid, s in ordered
        ]
    )


def problems(text: str, allowed: set[str], locale_pack: str) -> list[str]:
    """Why this model text can't be shown (empty = fine)."""
    found = []
    for ph in _PLACEHOLDER.findall(text):
        if "{{" + ph.strip() + "}}" not in allowed:
            found.append(f"placeholder not allowed for this finding: {{{{{ph}}}}}")
    for v in output_screen(text, locale_pack=locale_pack):
        found.append(f"{v.kind}: {v.detail}")
    return found


def _payload(specs: Sequence[tuple[str, CandidateSpec]]) -> dict[str, Any]:
    return {
        "findings": [
            {
                "id": fid,
                "kind": s.kind,
                "strength": s.strength,
                "subject": s.subject,
                "stats": s.stats,
                "placeholders": s.placeholders,
            }
            for fid, s in specs
        ]
    }


def rank_with_model(
    specs: Sequence[tuple[str, CandidateSpec]],
    mesh: MeshClient,
    *,
    locale_pack: str = "uk",
    before_call: Callable[[], None] | None = None,
    after_call: Callable[[Sequence[MeshResult]], None] | None = None,
) -> AnalystResult:
    """Rank and word `specs` (finding id, candidate) with the reasoning tier."""
    by_id = dict(specs)
    allowed = {fid: set(s.placeholders.values()) for fid, s in specs}
    schema = output_model([fid for fid, _ in specs])
    system = (PROMPTS_DIR / f"{PROMPT}.md").read_text(encoding="utf-8")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(_payload(specs), ensure_ascii=False)},
    ]
    out = AnalystResult(prompt_version=prompt_version(PROMPT))
    accepted: dict[str, Worded] = {}
    pending: dict[str, list[str]] = {}
    for round_ in (0, 1):
        if before_call is not None:
            before_call()
        result = mesh.structured(
            tier=ModelTier.REASONING,
            messages=messages,
            output=schema,
            name="analyst_rank",
            max_tokens=2500,
            locale_pack=locale_pack,
        )
        out.calls.extend(result.calls)
        if after_call is not None:
            after_call(result.calls)
        value: Any = result.value
        pending = {}
        for item in value.discarded:
            if item.finding_id not in accepted:
                out.discarded[str(item.finding_id)] = str(item.reason)
        for item in value.findings:
            fid = str(item.finding_id)
            if fid in accepted:
                continue
            issues = problems(item.headline, allowed[fid], locale_pack) + problems(
                item.explanation, allowed[fid], locale_pack
            )
            if issues:
                pending[fid] = issues
                continue
            out.discarded.pop(fid, None)
            accepted[fid] = Worded(fid, int(item.salience), item.headline, item.explanation, "llm")
        if not pending or round_ == 1:
            break
        out.repaired = True
        messages = [
            *messages,
            {"role": "assistant", "content": result.result.text},
            {
                "role": "user",
                "content": "These findings' wording broke the rules: "
                + json.dumps(pending)
                + " Return the full answer again, using only each finding's own placeholders "
                "for every amount, percentage, count and date.",
            },
        ]
    out.violations = pending
    # Wording that still fails, and findings the model left out, keep the template wording.
    for fid, spec in specs:
        if fid in accepted or fid in out.discarded:
            continue
        accepted[fid] = Worded(
            fid, deterministic_salience(spec), spec.headline, spec.detail, "template"
        )
    out.ranked = sorted(
        accepted.values(), key=lambda w: (-w.salience, -by_id[w.finding_id].score, w.finding_id)
    )
    return out
