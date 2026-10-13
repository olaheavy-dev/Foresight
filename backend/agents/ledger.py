"""Ledger Agent (docs/06 §4.1, docs/10 AGT-03): the model fallback for transactions the rules and
merchant memory could not place with confidence ≥ 0.85.

What goes to the model, and what never does (docs/05 §7.3, §7.4a):

- only spending-side rows (outflows). Inflows stay with the deterministic ladder and the user's
  confirmation (docs/06 H8): a model never decides that money is income;
- the cleaned narration (`normalised`: references, long numbers and card fragments already
  stripped), passed through `prepare_for_model` (quarantined, length-capped) and then
  `backend.mesh.redact` inside the Mesh client;
- an amount *band*, the direction, the weekday and the payment type. Never the exact amount, the
  balance, the account, the date or the raw description;
- rows flagged `suspicious_text` at import are not sent at all: they keep their rule result and
  go to the review queue.

The model chooses from the locale pack's category keys only (a JSON-schema enum); anything else
is rejected by validation. Its answer is stored as a new, append-only Categorisation with method
`llm`, and confident answers teach merchant memory (`learned`; a user correction always wins).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from backend.agents.cache import PROMPTS_DIR, prompt_version
from backend.agents.guard import prepare_for_model
from backend.finance_core.categorise.pack import CategorisationPack
from backend.finance_core.categorise.rules import REVIEW_THRESHOLD
from backend.finance_core.types import (
    Categorisation,
    CategorisationMethod,
    FlowKind,
    Transaction,
)
from backend.mesh.mesh_client import MeshClient, MeshResult, MeshSchemaError, ModelTier
from backend.mesh.redact import redact

PROMPT = "ledger_categorise"
UNCATEGORISED = "uncategorised"
BATCH_SIZE = 15  # keeps one fast-tier call well inside its 8 s timeout
MAX_NARRATION = 64  # docs/05 §7.4a L2
LLM_CONFIDENCE_CAP = 0.95  # a model answer never outranks a learned or user-confirmed one
LEARN_AT = 0.9  # only confident model answers teach merchant memory
# Output allowance per batch. Reasoning-capable fast models spend hidden reasoning tokens from
# the same allowance, so it is generous: a short allowance returns an empty answer.
BASE_MAX_TOKENS = 800
MAX_TOKENS_PER_ROW = 60
# Rule results that are settled facts about the flow, not guesses: never second-guessed.
_SETTLED_FLOWS = frozenset(
    {
        FlowKind.TRANSFER_OWN,
        FlowKind.CARD_SETTLEMENT,
        FlowKind.SAVINGS_INVESTMENT,
        FlowKind.CREDIT_CARD_BILL_UNITEMISED,
    }
)
# Categories a spending row may take: no income or refund keys for outflows.
_INFLOW_NATURES = frozenset({"income", "refund"})
_BANDS_MAJOR = (10, 20, 50, 100, 250, 500, 1000, 2500)
_SYMBOLS = {"GBP": "£", "EUR": "€", "USD": "$", "INR": "₹", "JPY": "¥"}
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def amount_band(amount_minor: int, currency: str, exponent: int = 2) -> str:
    """A range for the magnitude, e.g. "£20–50" (docs/05 §7.3): never the exact amount."""
    major = abs(amount_minor) / (10**exponent)
    sym = _SYMBOLS.get(currency.upper(), currency.upper() + " ")
    low = 0
    for edge in _BANDS_MAJOR:
        if major < edge:
            return f"{sym}{low}–{edge}"
        low = edge
    return f"over {sym}{_BANDS_MAJOR[-1]}"


@dataclass(frozen=True)
class Candidate:
    """One transaction the rules left below the review threshold."""

    txn: Transaction
    rule: Categorisation
    suspicious: bool = False


def is_candidate(txn: Transaction, rule: Categorisation, *, suspicious: bool = False) -> bool:
    """Should this row go to the model? Outflows below the threshold, not settled transfers,
    not user/memory answers, not suspicious text."""
    return (
        not suspicious
        and txn.amount_minor < 0
        and rule.confidence < REVIEW_THRESHOLD
        and rule.method in (CategorisationMethod.RULE,)
        and rule.flow_kind not in _SETTLED_FLOWS
    )


def allowed_categories(pack: CategorisationPack, *, outflow_only: bool) -> tuple[str, ...]:
    keys = [
        key
        for key, info in sorted(pack.categories.items())
        if not (outflow_only and info.nature in _INFLOW_NATURES)
    ]
    if UNCATEGORISED not in keys:
        keys.append(UNCATEGORISED)
    return tuple(keys)


def _describe(key: str, nature: str) -> str:
    words = key.replace(".", " — ").replace("_", " ")
    return f"{words} ({nature})" if nature else words


def batch_model(categories: Sequence[str]) -> type[BaseModel]:
    """The structured-output schema for one batch: the category is an enum of the pack's keys."""
    category_type: Any = Literal[tuple(categories)]
    item = create_model(
        "LedgerItem",
        __config__=ConfigDict(extra="forbid"),
        row=(int, Field(ge=0)),
        category=(category_type, ...),
        confidence=(float, Field(ge=0.0, le=1.0)),
    )
    return create_model(
        "LedgerBatch",
        __config__=ConfigDict(extra="forbid"),
        items=(list[item], ...),  # type: ignore[valid-type]
    )


@dataclass(frozen=True)
class PreparedRow:
    row: int
    payload: dict[str, Any]
    withheld: bool


def prepare_row(index: int, txn: Transaction, exponent: int = 2) -> PreparedRow:
    narration = txn.normalised or txn.description
    text, withheld = prepare_for_model(
        narration[: MAX_NARRATION * 2], "narration", payment_code=txn.channel.value.upper()
    )
    return PreparedRow(
        row=index,
        payload={
            "row": index,
            "narration": text[:MAX_NARRATION],
            "amount_band": amount_band(txn.amount_minor, txn.currency, exponent),
            "direction": "out" if txn.amount_minor < 0 else "in",
            "weekday": _WEEKDAYS[txn.posted_on.weekday()],
            "payment_type": txn.channel.value,
        },
        withheld=withheld,
    )


def messages_for(
    rows: Sequence[PreparedRow],
    categories: Sequence[str],
    pack: CategorisationPack,
    *,
    locale_pack: str = "uk",
) -> list[dict[str, str]]:
    # Rows are redacted here, before serialising, so person names in transfer narrations become
    # PERSON_n consistently across the batch; the Mesh client redacts the text again in transit.
    safe_rows = redact({"rows": [r.payload for r in rows]}, locale_pack=locale_pack)["rows"]
    payload = {
        "categories": [
            {
                "key": key,
                "description": _describe(
                    key, pack.categories[key].nature if key in pack.categories else ""
                ),
            }
            for key in categories
        ],
        "rows": safe_rows,
    }
    return [
        {"role": "system", "content": (PROMPTS_DIR / f"{PROMPT}.md").read_text(encoding="utf-8")},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


@dataclass
class LlmCategorisation:
    """Outcome of the model fallback over a set of rows."""

    results: dict[str, Categorisation] = field(default_factory=dict)  # txn id → model answer
    calls: list[MeshResult] = field(default_factory=list)
    sent: int = 0  # rows sent to the model
    withheld: int = 0  # rows whose text was withheld (suspicious) and so not sent
    invalid: int = 0  # items the model returned for unknown rows, or rows it skipped
    batches: int = 0
    failed_batches: int = 0  # still invalid after the repair retry: rows keep their rule answer
    prompt_version: str = ""

    @property
    def models(self) -> list[str]:
        return sorted({c.model for c in self.calls})


def categorise_with_model(
    txns: Sequence[Transaction],
    pack: CategorisationPack,
    mesh: MeshClient,
    *,
    locale_pack: str = "uk",
    outflow_only: bool = True,
    batch_size: int = BATCH_SIZE,
    max_batches: int | None = None,
    before_call: Callable[[], None] | None = None,
    after_call: Callable[[Sequence[MeshResult]], None] | None = None,
    exponent: int = 2,
) -> LlmCategorisation:
    """Send `txns` to the fast tier in deterministic batches (ordered by id) and validate the
    answers. Rows past `max_batches` are left alone (they stay in the review queue)."""
    out = LlmCategorisation(prompt_version=prompt_version(PROMPT))
    categories = allowed_categories(pack, outflow_only=outflow_only)
    schema = batch_model(categories)
    ordered = sorted(txns, key=lambda t: t.id)
    prepared: list[tuple[Transaction, PreparedRow]] = []
    for t in ordered:
        p = prepare_row(len(prepared), t, exponent)
        if p.withheld:
            out.withheld += 1
            continue
        prepared.append((t, p))
    batches = [prepared[i : i + batch_size] for i in range(0, len(prepared), batch_size)]
    if max_batches is not None:
        batches = batches[:max_batches]
    for batch in batches:
        rows = [
            PreparedRow(j, {**p.payload, "row": j}, p.withheld) for j, (_t, p) in enumerate(batch)
        ]
        if before_call is not None:
            before_call()
        out.batches += 1
        out.sent += len(rows)
        try:
            result = mesh.structured(
                tier=ModelTier.FAST,
                messages=messages_for(rows, categories, pack, locale_pack=locale_pack),
                output=schema,
                name="ledger_categorise",
                max_tokens=BASE_MAX_TOKENS + MAX_TOKENS_PER_ROW * len(rows),
                locale_pack=locale_pack,
            )
        except MeshSchemaError:
            # Degrade this batch only (docs/06 §10.1): its rows keep the rule answer and stay in
            # the review queue. Transport failures still propagate to the node's degrade path.
            out.failed_batches += 1
            out.invalid += len(rows)
            continue
        out.calls.extend(result.calls)
        if after_call is not None:
            after_call(result.calls)
        answered: set[int] = set()
        for item in getattr(result.value, "items", []):
            index = int(item.row)
            if index >= len(batch) or index in answered:
                out.invalid += 1
                continue
            answered.add(index)
            txn = batch[index][0]
            category = str(item.category)
            confidence = min(float(item.confidence), LLM_CONFIDENCE_CAP)
            out.results[txn.id] = Categorisation(
                transaction_id=txn.id,
                category_key=category,
                flow_kind=pack.default_flow_kind(category),
                method=CategorisationMethod.LLM,
                confidence=round(confidence if category != UNCATEGORISED else 0.3, 4),
                rationale=f"AI suggestion ({result.result.model})",
            )
        out.invalid += len(batch) - len(answered)
    return out


def merge(rule: Categorisation, model: Categorisation | None) -> Categorisation:
    """The hybrid answer for one row: the model's, unless it abstained or is no surer."""
    if model is None or model.category_key == UNCATEGORISED:
        return rule
    if model.category_key == rule.category_key:
        return rule if rule.confidence >= model.confidence else model
    return model if model.confidence > rule.confidence else rule


def memory_updates(
    txns: Mapping[str, Transaction], answers: Mapping[str, Categorisation]
) -> dict[str, str]:
    """Counterparty → category for confident model answers that agree across a counterparty's
    rows. A counterparty with conflicting answers teaches nothing."""
    seen: dict[str, set[str]] = {}
    for txn_id, c in answers.items():
        txn = txns.get(txn_id)
        if txn is None or not txn.counterparty or c.category_key == UNCATEGORISED:
            continue
        if c.confidence < LEARN_AT:
            seen.setdefault(txn.counterparty, set()).add("__weak__")
            continue
        seen.setdefault(txn.counterparty, set()).add(c.category_key)
    return {
        cpty: next(iter(keys))
        for cpty, keys in seen.items()
        if len(keys) == 1 and "__weak__" not in keys
    }


def weekday(on: date) -> str:
    return _WEEKDAYS[on.weekday()]
