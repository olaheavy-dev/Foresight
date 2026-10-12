"""Deterministic categorisation: merchant memory, locale-pack rules and the inflow ladder.

Order of precedence (docs/07 §3.3, docs/00 §6a):
1. user corrections in merchant memory (confidence 1.0), then learned memory (0.95);
2. outflows: card-bill, savings and self-transfer markers, then pack rules (merchants, patterns);
3. inflows: the direction-aware ladder (own transfer → from untracked → refund → payroll/government
   income → betting return → interest → inflow_unconfirmed);
4. the bank's own category as a weak prior (0.6);
5. fallback `uncategorised` (0.3).
Rows below `REVIEW_THRESHOLD` go to the Ledger Agent / human review (Stage 2). No model calls here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from backend.finance_core.categorise.normalise import parse_narration
from backend.finance_core.categorise.pack import CategorisationPack, Rule, contains_phrase
from backend.finance_core.types import (
    Categorisation,
    CategorisationMethod,
    Channel,
    FlowKind,
    Transaction,
)

REVIEW_THRESHOLD = 0.85


@dataclass(frozen=True)
class MemoryEntry:
    category_key: str
    source: str  # "user" | "learned"


@dataclass(frozen=True)
class CategoriseContext:
    """What the caller knows beyond the row itself."""

    self_aliases: tuple[str, ...] = ()  # the user's own name variants, uppercase
    paired_transfer_ids: frozenset[str] = frozenset()  # legs of own-account pairs
    memory: Mapping[str, MemoryEntry] = field(default_factory=dict)  # counterparty → category
    bank: str | None = None  # e.g. "monzo", for bank_category priors
    prior_debits: tuple[Transaction, ...] = ()  # earlier outflows, for refund matching


def needs_review(c: Categorisation) -> bool:
    return c.confidence < REVIEW_THRESHOLD


def _result(
    txn: Transaction,
    category: str,
    flow: FlowKind,
    method: CategorisationMethod,
    confidence: float,
    rationale: str,
) -> Categorisation:
    return Categorisation(txn.id, category, flow, method, confidence, rationale)


def _rule_match(rule: Rule, normalised: str) -> str | None:
    for merchant in rule.merchants:
        if contains_phrase(normalised, merchant):
            return merchant
    for pattern in rule.patterns:
        if pattern.search(normalised):
            return pattern.pattern
    return None


def _has_any(normalised: str, phrases: tuple[str, ...] | frozenset[str]) -> str | None:
    for phrase in phrases:
        if contains_phrase(normalised, phrase):
            return phrase
    return None


def _apply_rules(
    txn: Transaction, normalised: str, direction: str, pack: CategorisationPack
) -> Categorisation | None:
    for rule in pack.rules:
        if rule.direction not in (direction, "any"):
            continue
        token = _rule_match(rule, normalised)
        if token is not None:
            confidence = 0.92 if token in rule.merchants else 0.88
            return _result(
                txn,
                rule.category,
                rule.flow_kind,
                CategorisationMethod.RULE,
                confidence,
                f"matched '{token}'",
            )
    return None


def _is_refund(txn: Transaction, normalised: str, ctx: CategoriseContext) -> bool:
    if txn.counterparty is None:
        return False
    for debit in ctx.prior_debits:
        if (
            debit.counterparty == txn.counterparty
            and debit.amount_minor < 0
            and 0 <= (txn.posted_on - debit.posted_on).days <= 90
            and txn.amount_minor <= -debit.amount_minor
        ):
            return True
    return False


def _inflow_ladder(
    txn: Transaction, normalised: str, pack: CategorisationPack, ctx: CategoriseContext
) -> Categorisation:
    if txn.id in ctx.paired_transfer_ids:
        return _result(
            txn,
            "transfer.own",
            FlowKind.TRANSFER_OWN,
            CategorisationMethod.RULE,
            0.97,
            "paired with an outflow in another tracked account",
        )
    alias = _has_any(normalised, ctx.self_aliases)
    if alias:
        return _result(
            txn,
            "transfer.from_untracked",
            FlowKind.TRANSFER_FROM_UNTRACKED,
            CategorisationMethod.RULE,
            0.9,
            f"from your own name ('{alias}')",
        )
    marker = _has_any(normalised, pack.refund_markers)
    if marker or _is_refund(txn, normalised, ctx):
        why = (
            f"'{marker}' in narration" if marker else "matches an earlier payment to this merchant"
        )
        return _result(txn, "refund", FlowKind.REFUND, CategorisationMethod.RULE, 0.9, why)
    for payer in pack.government_payers:
        if payer.pattern.search(normalised):
            return _result(
                txn,
                payer.category,
                FlowKind.INCOME,
                CategorisationMethod.RULE,
                0.9,
                "government payer",
            )
    ruled = _apply_rules(txn, normalised, "in", pack)
    if ruled is not None:
        return ruled
    payroll = _has_any(normalised, pack.payroll_markers)
    if txn.channel == Channel.BACS_CREDIT and payroll:
        return _result(
            txn,
            "income.salary",
            FlowKind.INCOME,
            CategorisationMethod.RULE,
            0.9,
            f"Bacs credit from an employer-like payer ('{payroll}')",
        )
    if txn.channel == Channel.BACS_CREDIT:
        return _result(
            txn,
            "income.other",
            FlowKind.INCOME,
            CategorisationMethod.RULE,
            0.7,
            "Bacs credit; recurrence decides whether it is salary",
        )
    return _result(
        txn,
        "inflow_unconfirmed",
        FlowKind.INFLOW_UNCONFIRMED,
        CategorisationMethod.RULE,
        0.8,
        "money in we can't place; counted in the balance, never as income",
    )


def _outflow(
    txn: Transaction, normalised: str, pack: CategorisationPack, ctx: CategoriseContext
) -> Categorisation | None:
    if txn.id in ctx.paired_transfer_ids:
        return _result(
            txn,
            "transfer.own",
            FlowKind.TRANSFER_OWN,
            CategorisationMethod.RULE,
            0.97,
            "paired with an inflow in another tracked account",
        )
    marker = _has_any(normalised, pack.card_bill_markers)
    if marker:
        return _result(
            txn,
            "credit_card_bill_unitemised",
            FlowKind.CREDIT_CARD_BILL_UNITEMISED,
            CategorisationMethod.RULE,
            0.9,
            f"card bill ('{marker}'), card not tracked",
        )
    marker = _has_any(normalised, pack.savings_markers)
    if marker:
        return _result(
            txn,
            "savings_investment",
            FlowKind.SAVINGS_INVESTMENT,
            CategorisationMethod.RULE,
            0.9,
            f"savings ('{marker}')",
        )
    alias = _has_any(normalised, ctx.self_aliases) or _has_any(
        normalised, pack.self_transfer_markers
    )
    if alias:
        return _result(
            txn,
            "transfer.untracked",
            FlowKind.TRANSFER_TO_UNTRACKED,
            CategorisationMethod.RULE,
            0.88,
            f"to your own account ('{alias}')",
        )
    return _apply_rules(txn, normalised, "out", pack)


def categorise(
    txn: Transaction, pack: CategorisationPack, ctx: CategoriseContext | None = None
) -> Categorisation:
    ctx = ctx or CategoriseContext()
    normalised = txn.normalised or parse_narration(txn.description, None, pack).normalised
    key = txn.counterparty or normalised
    remembered = ctx.memory.get(key)
    if remembered is not None:
        user = remembered.source == "user"
        return _result(
            txn,
            remembered.category_key,
            pack.default_flow_kind(remembered.category_key),
            CategorisationMethod.USER if user else CategorisationMethod.MEMORY,
            1.0 if user else 0.95,
            "your earlier correction" if user else "learned for this merchant",
        )
    if txn.amount_minor > 0:
        return _inflow_ladder(txn, normalised, pack, ctx)
    ruled = _outflow(txn, normalised, pack, ctx)
    if ruled is not None:
        return ruled
    if txn.bank_category and ctx.bank:
        prior = pack.bank_category_priors.get(ctx.bank, {}).get(txn.bank_category.lower())
        if prior and prior != "other":
            return _result(
                txn,
                prior,
                pack.default_flow_kind(prior),
                CategorisationMethod.RULE,
                0.6,
                f"bank category '{txn.bank_category}' (weak prior)",
            )
    if txn.channel == Channel.CASH:
        return _result(
            txn,
            "cash.withdrawal",
            FlowKind.SPENDING,
            CategorisationMethod.RULE,
            0.9,
            "cash withdrawal",
        )
    return _result(
        txn, "uncategorised", FlowKind.SPENDING, CategorisationMethod.RULE, 0.3, "no rule matched"
    )


def learn(
    memory: Mapping[str, MemoryEntry], counterparty: str, category_key: str, source: str
) -> dict[str, MemoryEntry]:
    """Return updated merchant memory. A user correction always wins over learned entries."""
    updated = dict(memory)
    existing = updated.get(counterparty)
    if existing is not None and existing.source == "user" and source != "user":
        return updated
    updated[counterparty] = MemoryEntry(category_key, source)
    return updated
