"""Semantic validation and composition (docs/08 §6, §7a, §9).

Pydantic checks shape. This module checks what shape cannot express: the answer skeleton (slot
order and budgets, the fixed tab set), one currency per block and per response (V-20), no
numerals in plan text, and the fallbacks: an unknown or invalid block becomes a Narrative with a
logged reason, and an over-budget Overview moves its overflow to a tab instead of dropping it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError

from backend.app.ui_contracts.blocks import (
    BLOCK_TYPES,
    Block,
    FinancialMetricGroup,
    Narrative,
    TextSegment,
    TransactionTable,
)
from backend.app.ui_contracts.plan import (
    BlockPlan,
    ClarifyingQuestionPlan,
    FinancialMetricGroupPlan,
    NarrativePlan,
    ResponsePlan,
)
from backend.app.ui_contracts.primitives import (
    CALC_REF_PATTERN,
    SLOT_ORDER,
    TAB_ORDER,
    FollowUpAction,
    FollowUpPlan,
    OverviewPlacement,
    OverviewSlot,
    TabName,
    TabPlacement,
)
from backend.app.ui_contracts.response import AgentResponse

log = logging.getLogger("foresight.ui_contracts")

IssueCode = Literal[
    "skeleton_slot_order", "skeleton_slot_type", "skeleton_budget", "skeleton_main_visual",
    "skeleton_tab_duplicate", "overview_overflow", "currency_mix", "block_currency_missing",
    "narrative_numeral", "placeholder_invalid", "unknown_block", "invalid_block",
    "invalid_follow_up",
]  # fmt: skip


@dataclass(frozen=True)
class Issue:
    code: IssueCode
    message: str
    block_id: str | None = None


def _log(issue: Issue) -> Issue:
    log.warning("%s: %s", issue.code, issue.message, extra={"block_id": issue.block_id})
    return issue


# --- Answer skeleton (§7a) ---------------------------------------------------------------------

SLOT_TYPES: dict[OverviewSlot, frozenset[str]] = {
    "verdict": frozenset({"Narrative", "ClarifyingQuestion"}),
    "key_numbers": frozenset({"FinancialMetricGroup"}),
    "main_visual": frozenset({
        "ScenarioComparison", "CashFlowForecastChart", "SpendingBreakdownChart", "GoalProjection",
        "RiskAssessment", "TransactionTable", "EvidencePanel", "InterventionCard",
        # FinancialMetricGroup: the goal outlook when no goal exists (§7a goal_status row).
        "FinancialMetricGroup",
    }),
    "what_to_do": frozenset({"InterventionCard"}),
    "evidence": frozenset({"EvidencePanel"}),
}  # fmt: skip
SLOT_MAX: dict[OverviewSlot, int] = {
    "verdict": 1, "key_numbers": 1, "main_visual": 3, "what_to_do": 1, "evidence": 1,
}  # fmt: skip
MAX_KEY_NUMBERS = 3
MAX_MAIN_VISUAL_ROWS = 10
# Where an overflowing block goes (§7a "moved to its intent's tab, or How it was checked").
HOME_TAB: dict[str, TabName] = {
    "Narrative": "details", "ClarifyingQuestion": "details",
    "FinancialMetricGroup": "details", "SpendingBreakdownChart": "details",
    "CashFlowForecastChart": "details", "GoalProjection": "details", "RiskAssessment": "details",
    "ScenarioComparison": "recommendation", "InterventionCard": "recommendation",
    "TransactionTable": "transactions", "EvidencePanel": "checked",
    "AgentExecutionTimeline": "checked",
}  # fmt: skip


def _main_visual_ok(types: Sequence[str]) -> bool:
    """Exactly one main visual; or up to three InterventionCards (advice_request); or the
    risk_check pair, RiskAssessment with CashFlowForecastChart."""
    if len(types) == 1:
        return True
    if 1 < len(types) <= 3 and all(t == "InterventionCard" for t in types):
        return True
    return sorted(types) == ["CashFlowForecastChart", "RiskAssessment"]


def _get(block: object, name: str) -> Any:
    """Read a field from a model or from raw JSON, so the checks also run on unparsed blocks."""
    return block.get(name) if isinstance(block, dict) else getattr(block, name, None)


def _slot(block: object) -> OverviewSlot | None:
    placement = _get(block, "placement")
    if _get(placement, "area") == "overview" and _get(placement, "slot") in SLOT_ORDER:
        return _get(placement, "slot")  # type: ignore[no-any-return]
    return None


def _tab(block: object) -> TabName | None:
    placement = _get(block, "placement")
    if _get(placement, "area") == "tab" and _get(placement, "tab") in TAB_ORDER:
        return _get(placement, "tab")  # type: ignore[no-any-return]
    return None


def _type(block: object) -> str:
    return str(_get(block, "type") or "")


def _count(block: object, name: str) -> int:
    items = _get(block, name)
    return len(items) if isinstance(items, list | tuple) else 0


def _bid(block: object) -> str | None:
    value = _get(block, "block_id")
    return value if isinstance(value, str) else None


def _verdict_only(blocks: Sequence[object]) -> bool:
    slots = {_slot(b) for b in blocks} - {None}
    return slots == {"verdict"}


def check_skeleton(blocks: Sequence[object]) -> list[Issue]:
    """Report every way the blocks (models or raw JSON) break the answer skeleton."""
    issues: list[Issue] = []
    overview = [b for b in blocks if _slot(b) is not None]
    order = [SLOT_ORDER.index(s) for b in overview if (s := _slot(b)) is not None]
    if order != sorted(order):
        issues.append(Issue("skeleton_slot_order", "Overview blocks are not in slot order"))
    for slot in SLOT_ORDER:
        here = [b for b in overview if _slot(b) == slot]
        for b in here:
            if _type(b) not in SLOT_TYPES[slot]:
                issues.append(
                    Issue("skeleton_slot_type", f"{_type(b)} cannot fill {slot}", _bid(b))
                )
        if slot == "main_visual":
            continue
        if len(here) > SLOT_MAX[slot]:
            issues.append(Issue("skeleton_budget", f"{len(here)} blocks in {slot}"))
    for b in overview:
        if _type(b) == "FinancialMetricGroup" and _slot(b) == "key_numbers":
            if _count(b, "metrics") > MAX_KEY_NUMBERS:
                issues.append(Issue("skeleton_budget", "more than 3 key numbers", _bid(b)))
        if _type(b) == "TransactionTable" and _count(b, "rows") > MAX_MAIN_VISUAL_ROWS:
            issues.append(Issue("skeleton_budget", "main-visual table over 10 rows", _bid(b)))
    visuals = [_type(b) for b in overview if _slot(b) == "main_visual"]
    if not (_main_visual_ok(visuals) or (not visuals and _verdict_only(blocks))):
        issues.append(
            Issue("skeleton_main_visual", f"Overview needs exactly one main visual, has {visuals}")
        )
    for tab in TAB_ORDER:
        types = [_type(b) for b in blocks if _tab(b) == tab]
        for t in sorted({t for t in types if types.count(t) > 1}):
            issues.append(Issue("skeleton_tab_duplicate", f"{t} appears twice in {tab}"))
    return issues


def visible_tabs(blocks: Sequence[object]) -> list[TabName]:
    """The fixed tab set in its fixed order, with empty tabs hidden (never reordered)."""
    present = {_tab(b) for b in blocks}
    return [t for t in TAB_ORDER if t in present]


def _move(block: Any, tab: TabName) -> Any:
    return block.model_copy(update={"placement": TabPlacement(area="tab", tab=tab)})


def enforce_skeleton(blocks: Sequence[Any]) -> tuple[list[Any], list[Issue]]:
    """Re-order the Overview into slot order and move anything over its budget to a tab.

    Overflow goes to the block type's home tab, or to How it was checked when that tab already
    has one of its type; only a block that fits nowhere is dropped. Every move is logged as
    `overview_overflow`. A missing main visual is reported, not invented: the caller falls back
    to the intent's deterministic template (§9).
    """
    issues: list[Issue] = []
    kept: dict[OverviewSlot, list[Any]] = {s: [] for s in SLOT_ORDER}
    overflow: list[Any] = []
    tabbed: list[Any] = [b for b in blocks if _tab(b) is not None]

    overview = sorted(
        (b for b in blocks if _slot(b) is not None),
        key=lambda b: SLOT_ORDER.index(_slot(b)),  # stable: plan order within a slot
    )
    for b in overview:
        slot = _slot(b)
        assert slot is not None
        here = kept[slot]
        fits = _type(b) in SLOT_TYPES[slot]
        if slot == "main_visual":
            fits = fits and _main_visual_ok([_type(x) for x in here] + [_type(b)])
            if isinstance(b, TransactionTable) and len(b.rows) > MAX_MAIN_VISUAL_ROWS:
                fits = False
        else:
            fits = fits and len(here) < SLOT_MAX[slot]
        if not fits:
            overflow.append(b)
            continue
        if isinstance(b, FinancialMetricGroup) and len(b.metrics) > MAX_KEY_NUMBERS:
            head = b.model_copy(update={"metrics": b.metrics[:MAX_KEY_NUMBERS]})
            rest = b.model_copy(
                update={"block_id": f"{b.block_id}-more", "metrics": b.metrics[MAX_KEY_NUMBERS:]}
            )
            here.append(head)
            overflow.append(rest)
            continue
        here.append(b)

    for b in overflow:
        taken = {(_tab(x), _type(x)) for x in tabbed}
        for tab in (HOME_TAB.get(_type(b), "checked"), "checked"):
            if (tab, _type(b)) not in taken:
                tabbed.append(_move(b, tab))
                issues.append(
                    _log(Issue("overview_overflow", f"{_type(b)} moved to {tab}", _bid(b)))
                )
                break
        else:
            issues.append(
                _log(Issue("skeleton_tab_duplicate", f"{_type(b)} fits no tab; dropped", _bid(b)))
            )

    seen: set[tuple[TabName | None, str]] = set()
    tabs_out: list[Any] = []
    for tab in TAB_ORDER:
        for b in tabbed:
            if _tab(b) != tab:
                continue
            key = (tab, _type(b))
            if key in seen:  # ≤ 1 block of each type per tab; excess truncated by plan order
                issues.append(
                    _log(Issue("skeleton_tab_duplicate", f"second {key[1]} in {tab}", _bid(b)))
                )
                continue
            seen.add(key)
            tabs_out.append(b)

    out = [b for s in SLOT_ORDER for b in kept[s]] + tabs_out
    if not kept["main_visual"] and not _verdict_only(out):
        issues.append(Issue("skeleton_main_visual", "no main visual; use the intent template"))
    return out, issues


# --- Currency (V-20, §6 "one currency per block") ----------------------------------------------


def money_values(node: object) -> Iterator[dict[str, Any]]:
    """Every money value (`kind: "money"`) anywhere inside JSON."""
    if isinstance(node, dict):
        if node.get("kind") == "money" and "minor" in node:
            yield node
        for item in node.values():
            yield from money_values(item)
    elif isinstance(node, list):
        for item in node:
            yield from money_values(item)


def _json(node: object) -> Any:
    return node.model_dump(mode="json", by_alias=True) if isinstance(node, BaseModel) else node


def check_currency(response: AgentResponse | dict[str, Any]) -> list[Issue]:
    """One currency per block and per response; there is no FX conversion (`00` §6c).
    Accepts a parsed response or raw JSON."""
    raw = _json(response)
    home = raw.get("currency")
    issues: list[Issue] = []
    for block in raw.get("blocks") or []:
        found = {m.get("currency") for m in money_values(block)}
        bid = _bid(block)
        if found and not block.get("currency"):
            issues.append(Issue("block_currency_missing", "money without a block currency", bid))
        declared = block.get("currency") or home
        if found - {declared}:
            mixed = sorted(map(str, found))
            issues.append(Issue("currency_mix", f"{mixed} in a {declared} block", bid))
        if declared != home:
            issues.append(Issue("currency_mix", f"{declared} block in a {home} response", bid))
    for m in money_values(raw.get("follow_ups") or []):
        if m.get("currency") != home:
            issues.append(Issue("currency_mix", f"{m.get('currency')} follow-up"))
    return issues


# --- No numerals in plan text (§5.0, §3.4) -----------------------------------------------------

PLACEHOLDER = re.compile(r"\{\{\s*([^{}|]+?)\s*(?:\|\s*([a-z_]+)\s*)?\}\}")
NUMERAL = re.compile(r"[£$€₹¥]?\s?\d(?:[\d,.]*\d)?\s?%?")
_CALC_REF = re.compile(CALC_REF_PATTERN)
_MENTION = re.compile(r"^(fnd|rec|ver)_[0-9A-HJKMNP-TV-Z]{26}$")
_FORMATS = {"money", "percent", "pct_change", "pp_change", "count", "date", "days"}


def numeric_literals(text: str) -> list[str]:
    """Digits outside `{{ }}` placeholders. Plan text may not state a number itself."""
    return [m.group().strip() for m in NUMERAL.finditer(PLACEHOLDER.sub(" ", text))]


def placeholder_errors(text: str) -> list[str]:
    errors = []
    for m in PLACEHOLDER.finditer(text):
        ref, fmt = m.group(1), m.group(2)
        if _CALC_REF.match(ref):
            if fmt not in _FORMATS:
                errors.append(f"{m.group()} needs a format from {sorted(_FORMATS)}")
        elif not (_MENTION.match(ref) and fmt is None):
            errors.append(f"{m.group()} is not a calc value or a fnd_/rec_/ver_ mention")
    return errors


def _plan_texts(plan: ResponsePlan) -> Iterator[tuple[str, str]]:
    for i, block in enumerate(plan.blocks):
        where = f"blocks.{i}"
        if isinstance(block, NarrativePlan):
            yield f"{where}.text", block.text
        elif isinstance(block, ClarifyingQuestionPlan):
            yield f"{where}.question", block.question
            for j, option in enumerate(block.options):
                yield f"{where}.options.{j}.label", option.label
        elif isinstance(block, FinancialMetricGroupPlan):
            for j, metric in enumerate(block.metrics):
                yield f"{where}.metrics.{j}.label", metric.label
                if metric.compare_label:
                    yield f"{where}.metrics.{j}.compare_label", metric.compare_label
    for i, follow_up in enumerate(plan.follow_ups):
        yield f"follow_ups.{i}.label", follow_up.label


def check_plan_text(plan: ResponsePlan) -> list[Issue]:
    issues = []
    for where, text in _plan_texts(plan):
        if found := numeric_literals(text):
            issues.append(Issue("narrative_numeral", f"{where}: {found}"))
        issues += [Issue("placeholder_invalid", f"{where}: {e}") for e in placeholder_errors(text)]
    return issues


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def strip_numeral_sentences(text: str) -> str:
    """After a failed repair, drop each sentence that states a number (§6 Step 1)."""
    return " ".join(s for s in _SENTENCE.split(text) if not numeric_literals(s)).strip()


# --- Fallbacks (§9) ----------------------------------------------------------------------------

BLOCK_LABELS = {
    "FinancialMetricGroup": "key numbers", "SpendingBreakdownChart": "spending chart",
    "CashFlowForecastChart": "cash-flow chart", "ScenarioComparison": "scenario comparison",
    "TransactionTable": "transactions", "RiskAssessment": "risk summary",
    "InterventionCard": "recommendation", "GoalProjection": "goal projection",
    "EvidencePanel": "evidence", "AgentExecutionTimeline": "agent timeline",
    "ClarifyingQuestion": "question", "Narrative": "explanation",
}  # fmt: skip
_PLAN_BLOCK: TypeAdapter[Any] = TypeAdapter(BlockPlan)
_BLOCK: TypeAdapter[Any] = TypeAdapter(Block)
_FOLLOW_UP_PLAN: TypeAdapter[Any] = TypeAdapter(FollowUpPlan)
_FOLLOW_UP: TypeAdapter[Any] = TypeAdapter(FollowUpAction)
_PLACEMENT: TypeAdapter[Any] = TypeAdapter(OverviewPlacement | TabPlacement)


def fallback_text(block_type: object) -> str:
    label = BLOCK_LABELS.get(block_type, "this view") if isinstance(block_type, str) else None
    what = f"the {label}" if label and label != "this view" else "this view"
    return f"I couldn't show {what}; the figures are in the evidence."


def _reason(raw: object, exc: ValidationError | None) -> tuple[IssueCode, str]:
    block_type = raw.get("type") if isinstance(raw, dict) else None
    if block_type not in BLOCK_TYPES:
        return "unknown_block", f"unknown block type {block_type!r}"
    assert exc is not None
    first = exc.errors()[0]
    where = ".".join(str(p) for p in first["loc"])
    return "invalid_block", f"{block_type} invalid at {where}: {first['msg']}"


def _valid_follow_ups(items: object, adapter: TypeAdapter[Any], issues: list[Issue]) -> list[Any]:
    """Invalid follow-ups are dropped, never repaired (§6: "drop follow-up")."""
    kept = []
    for i, item in enumerate(items if isinstance(items, list) else []):
        try:
            kept.append(adapter.validate_python(item))
        except ValidationError as exc:
            first = exc.errors()[0]
            issues.append(_log(Issue("invalid_follow_up", f"follow_ups.{i}: {first['msg']}")))
    return kept


def parse_plan(raw: dict[str, Any]) -> tuple[ResponsePlan, list[Issue]]:
    """Validate a plan block by block. An unknown or invalid block becomes a fallback Narrative
    with a logged reason; an invalid envelope still raises (the caller's one repair attempt)."""
    issues: list[Issue] = []
    blocks: list[Any] = []
    for i, item in enumerate(raw.get("blocks") or []):
        try:
            blocks.append(_PLAN_BLOCK.validate_python(item))
        except ValidationError as exc:
            code, why = _reason(item, exc)
            issues.append(_log(Issue(code, f"blocks.{i}: {why}")))
            block_type = item.get("type") if isinstance(item, dict) else None
            blocks.append(NarrativePlan(type="Narrative", text=fallback_text(block_type)))
    follow_ups = _valid_follow_ups(raw.get("follow_ups"), _FOLLOW_UP_PLAN, issues)
    plan = ResponsePlan.model_validate({**raw, "blocks": blocks, "follow_ups": follow_ups})
    return plan, issues


def _fallback_block(item: object, index: int) -> Narrative:
    data = item if isinstance(item, dict) else {}
    try:
        placement = _PLACEMENT.validate_python(data.get("placement"))
    except ValidationError:
        placement = TabPlacement(area="tab", tab="details")
    evidence = data.get("evidence")
    return Narrative(
        type="Narrative",
        block_id=str(data.get("block_id") or f"fallback-{index}"),
        placement=placement,
        evidence=[e for e in evidence if isinstance(e, str)] if isinstance(evidence, list) else [],
        segments=[TextSegment(kind="text", text=fallback_text(data.get("type")))],
    )


def parse_response(raw: dict[str, Any]) -> tuple[AgentResponse, list[Issue]]:
    """Validate hydrated blocks one by one (§6 Step 2): a block that fails is replaced by a
    Narrative saying so, and the response is marked degraded."""
    issues: list[Issue] = []
    blocks: list[Any] = []
    for i, item in enumerate(raw.get("blocks") or []):
        try:
            blocks.append(_BLOCK.validate_python(item))
        except ValidationError as exc:
            code, why = _reason(item, exc)
            issues.append(_log(Issue(code, f"blocks.{i}: {why}", _bid(item))))
            blocks.append(_fallback_block(item, i))
    degraded = bool(issues)
    follow_ups = _valid_follow_ups(raw.get("follow_ups"), _FOLLOW_UP, issues)
    status = "degraded" if degraded else raw.get("status")
    response = AgentResponse.model_validate(
        {**raw, "blocks": blocks, "follow_ups": follow_ups, "status": status}
    )
    return response, issues


__all__ = [
    "Issue",
    "check_currency",
    "check_plan_text",
    "check_skeleton",
    "enforce_skeleton",
    "numeric_literals",
    "parse_plan",
    "parse_response",
    "strip_numeral_sentences",
    "visible_tabs",
]
