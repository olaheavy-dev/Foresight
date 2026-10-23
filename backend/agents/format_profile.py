"""LLM-proposed CSV FormatProfile for unseen layouts (docs/10 ING-13, docs/06 §9 H1, 09 §4.1.3).

Only when no saved or built-in profile matches and the header heuristic is unsure. The model sees
(docs/05 §7.3):

- the header titles, each through `prepare_for_model` (an instruction-like header is withheld);
- at most five sample rows reduced to *shapes*: digits become `9`, words become `<TEXT>`, month
  names `<MON>`. Never an amount, a balance, a name or a reference.

It answers with a column index per role. The proposal is checked deterministically: the indexes
must exist and differ, the roles must make a usable table (date, description, and an amount or a
money-in/money-out pair), and the importer must parse the file with it. The user confirms the
mapping once (H1); the confirmed profile is saved and every later file with the same header
matches it by signature, with no model call.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.agents.cache import PROMPTS_DIR, prompt_version
from backend.agents.guard import prepare_for_model
from backend.finance_core.importers.profiles import FormatProfile, normalise_header
from backend.llm.client import ModelClient, ModelResult, ModelTier

PROMPT = "ledger_format_profile"
MAX_SAMPLE_ROWS = 5
ROLES = (
    "date",
    "description",
    "amount",
    "money_in",
    "money_out",
    "balance",
    "id",
    "bank_category",
    "bank_type",
    "currency",
    "time",
)
_MONTHS = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.IGNORECASE
)


def shape(cell: str) -> str:
    """A cell reduced to its shape: '−1,234.56' → '-9,999.99', '12 Mar 2026' → '99 <MON> 9999',
    'TESCO STORES' → '<TEXT>'. Never the value itself."""
    text = cell.strip()
    if not text:
        return ""
    text = _MONTHS.sub("<MON>", text)
    if re.search(r"[A-Za-z]", text.replace("<MON>", "")):
        return "<TEXT>"
    return re.sub(r"\d", "9", text)


class ColumnProposal(BaseModel):
    """The model's answer: a 0-based column index per role, or null when absent."""

    model_config = ConfigDict(extra="forbid")

    date: int | None
    description: int | None
    amount: int | None
    money_in: int | None
    money_out: int | None
    balance: int | None
    id: int | None
    bank_category: int | None
    bank_type: int | None
    currency: int | None
    time: int | None
    sign_convention: Literal["signed", "in_out"]
    confidence: float = Field(ge=0.0, le=1.0)


@dataclass
class Proposal:
    profile: FormatProfile | None
    problems: list[str] = field(default_factory=list)
    calls: list[ModelResult] = field(default_factory=list)
    withheld_headers: int = 0
    prompt_version: str = ""
    confidence: float | None = None


def _payload(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> tuple[dict[str, Any], int]:
    shown = []
    withheld = 0
    for i, h in enumerate(headers):
        text, flagged = prepare_for_model(h, "header")
        withheld += flagged
        shown.append({"index": i, "title": text})
    samples = [[shape(c) for c in row] for row in list(rows)[:MAX_SAMPLE_ROWS]]
    return {"columns": shown, "sample_rows": samples}, withheld


def validate(proposal: ColumnProposal, headers: Sequence[str]) -> tuple[dict[str, int], list[str]]:
    roles = {r: getattr(proposal, r) for r in ROLES if getattr(proposal, r) is not None}
    issues: list[str] = []
    for role, idx in roles.items():
        if not 0 <= idx < len(headers) or not headers[idx].strip():
            issues.append(f"{role}: column {idx} does not exist")
    if len(set(roles.values())) != len(roles):
        issues.append("two roles point at the same column")
    if "date" not in roles or "description" not in roles:
        issues.append("a date and a description column are required")
    has_amount = "amount" in roles or ("money_in" in roles and "money_out" in roles)
    if not has_amount:
        issues.append("an amount column, or money-in and money-out columns, are required")
    return roles, issues


def profile_from(roles: dict[str, int], headers: Sequence[str], convention: str) -> FormatProfile:
    norm = [normalise_header(h) for h in headers]
    if "money_in" in roles and "money_out" in roles:
        convention = "in_out"
    elif "amount" in roles:
        convention = "signed"
    signature = tuple(n for n in norm if n)
    digest = hashlib.sha256("|".join(signature).encode()).hexdigest()[:12]
    return FormatProfile(
        profile_id=f"proposed.{digest}",
        label="Columns proposed for this layout",
        header_signature=signature,
        columns={role: (norm[idx],) for role, idx in roles.items()},
        sign_convention=convention,
        skip_zero_amount=True,
        origin="proposed",
        notes=("proposed by the Ledger Agent from header titles and value shapes",),
    )


def propose(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    model_client: ModelClient,
    *,
    locale_pack: str = "uk",
) -> Proposal:
    """One fast-tier call. The result stays `origin="proposed"` until the user confirms it."""
    payload, withheld = _payload(headers, rows)
    system = (PROMPTS_DIR / f"{PROMPT}.md").read_text(encoding="utf-8")
    result = model_client.structured(
        tier=ModelTier.FAST,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        output=ColumnProposal,
        name="format_profile",
        max_tokens=1200,
        locale_pack=locale_pack,
    )
    value = result.value
    roles, issues = validate(value, headers)
    out = Proposal(
        profile=None if issues else profile_from(roles, headers, value.sign_convention),
        problems=issues,
        calls=list(result.calls),
        withheld_headers=withheld,
        prompt_version=prompt_version(PROMPT),
        confidence=value.confidence,
    )
    return out


def confirmed(profile: FormatProfile) -> FormatProfile:
    """The user confirmed the mapping (H1): saved and reused with no model call."""
    return replace(profile, origin="user_confirmed", label="Confirmed columns for this layout")
