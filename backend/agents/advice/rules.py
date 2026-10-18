"""The Verifier's deterministic rules (docs/06 §5). They run before the LLM judge and can block.

Each rule returns a `RuleResult` with `rule_id = "V-xx@<version>"` so the audit trail stays
interpretable after rules change. Critiques fed back to the Advisor are templates filled with the
rule's evidence, never model text.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from backend.agents.advice.impact import TIMING_ACTIONS, Impact
from backend.agents.advice.models import InterventionProposal, RuleResult
from backend.agents.advice.world import AdviceWorld
from backend.agents.guard.output import numerals_outside_placeholders, output_screen

VERSION = "1"
MATERIAL_MONTHLY_MINOR = 1000  # V-05: ≥ £10 a month …
MATERIAL_RISK_POINTS = 0.05  # … or ≥ 5 percentage points less chance of going below the buffer
MAX_CUT = 0.40  # V-04: a cap may be at most 40% below the 3-month median
IMPACT_TOLERANCE = 0.01  # V-06: ±1%

# V-04 (FR-50c): these can be rescheduled, never cut or cancelled.
NO_CUT_PREFIXES = (
    "housing.",
    "utilities.energy",
    "utilities.water",
    "insurance",
    "debt.",
)
NOT_SPEND = ("income", "refund", "transfer.", "betting_return")  # V-16: never "savings"
CUT_ACTIONS = frozenset({"cap_category", "cancel_recurring", "downgrade_recurring"})
GENERIC_PHRASES = (
    "spend less",
    "save more",
    "track your expenses",
    "track your spending",
    "make a budget",
    "create a budget",
    "cut back",
    "be more careful",
    "consider reviewing",
    "review your subscriptions",
    "try to",
)
PERSON_ATTRIBUTION = re.compile(
    r"(?i)\b(your partner|your (wife|husband|girlfriend|boyfriend|spouse)|"
    r"(he|she) (spent|spends|ordered)|partner's)\b"
)
MORALISING = re.compile(
    r"(?i)\b(addict(ion|ed)?|problem|wast(e|ing|eful)|irresponsible|quit|reckless|habit)\b"
)
CURRENCY_SYMBOLS = re.compile(r"[£$€₹¥]")
CURRENCY_SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$", "INR": "₹", "JPY": "¥"}


def _result(
    rule: str, passed: bool, detail: str = "", severity: str = "block", **evidence: Any
) -> RuleResult:
    return RuleResult(
        rule_id=f"{rule}@{VERSION}",
        passed=passed,
        severity=severity,  # type: ignore[arg-type]
        detail=detail,
        evidence=evidence,
    )


def _text(p: InterventionProposal) -> str:
    return f"{p.title}\n{p.rationale}"


def _category(p: InterventionProposal, world: AdviceWorld) -> str | None:
    if "category_key" in p.params:
        return str(p.params["category_key"])
    ob = world.obligation(str(p.params.get("recurring_id") or ""))
    return ob.category_key if ob else None


def v01(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    dangling = [r.id for r in p.trigger_refs if not world.resolve(r)]
    return _result(
        "V-01", not dangling, "cited evidence not found" if dangling else "", dangling=dangling
    )


def v02(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    ok = any(
        r.kind in ("finding", "forecast", "simulation") and r.role == "trigger"
        for r in p.trigger_refs
    )
    return _result("V-02", ok, "" if ok else "no finding or forecast triggers it")


def v03(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    if p.action == "cap_category":
        cat = str(p.params.get("category_key") or "")
        ok = world.seen_recently(cat)
        return _result(
            "V-03", ok, "" if ok else f"no {cat} spending in the last 90 days", target=cat
        )
    if p.action in ("cancel_recurring", "downgrade_recurring", "reschedule_transfer"):
        key = str(p.params.get("recurring_id") or "")
        ok = world.obligation_active(key)
        return _result("V-03", ok, "" if ok else f"no active recurring payment {key}", target=key)
    return _result("V-03", True)


def v04(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    cat = _category(p, world)
    if p.action in CUT_ACTIONS and cat and cat.startswith(NO_CUT_PREFIXES):
        return _result(
            "V-04", False, f"{cat} is essential: it can be rescheduled, not cut", category=cat
        )
    if p.action != "cap_category":
        return _result("V-04", True)
    cap = p.params.get("monthly_cap_minor")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
        return _result("V-04", False, "the cap is not a whole amount", cap=cap)
    median = world.median_3x30(str(cat))
    floor = int(median * (1 - MAX_CUT))
    ok = cap >= floor
    return _result(
        "V-04",
        ok,
        "" if ok else "the cap is more than 40% below the usual 3-month level",
        cap_minor=cap,
        median_3x30_minor=median,
        min_cap_minor=floor,
    )


def v05(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    monthly = impact.monthly_minor
    if monthly is not None and monthly >= MATERIAL_MONTHLY_MINOR:
        return _result("V-05", True, monthly_minor=monthly)
    if p.action in ("set_aside_amount", "build_buffer"):
        amount = p.params.get("amount_minor")
        ok = isinstance(amount, int) and amount >= MATERIAL_MONTHLY_MINOR
        return _result("V-05", ok, "" if ok else "too small to matter", amount_minor=amount)
    before, after = impact.risk_before, impact.risk_after
    if before is None or after is None:
        why = impact.error or "no buffer or forecast to measure the risk against"
        return _result("V-05", False, f"impact couldn't be checked: {why}")
    drop = round(before - after, 4)
    ok = drop >= MATERIAL_RISK_POINTS
    return _result(
        "V-05",
        ok,
        "" if ok else "less than £10 a month and under 5 points less risk",
        monthly_minor=monthly,
        risk_before=before,
        risk_after=after,
    )


_AMOUNT = re.compile(r"[£$€₹¥]\s?(\d[\d,]*(?:\.\d+)?)")


def v06(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    recomputed = impact.monthly_minor
    if recomputed is None:
        if impact.basis == "cross_currency":
            return _result("V-06", True, "no single-currency basis (see V-20)")
        return _result(
            "V-06",
            False,
            "the impact couldn't be recomputed",
            claimed=p.claimed_monthly_impact_minor,
        )
    tolerance = abs(recomputed) * IMPACT_TOLERANCE
    off = abs(p.claimed_monthly_impact_minor - recomputed)
    figures = [
        round(float(a.replace(",", "")) * 100) for a in _AMOUNT.findall(p.claimed_impact_text or "")
    ]
    text_off = [f for f in figures if abs(f - recomputed) > max(tolerance, 1)]
    ok = off <= tolerance and not text_off
    return _result(
        "V-06",
        ok,
        "" if ok else "the claimed impact doesn't match the recomputed impact",
        claimed=p.claimed_monthly_impact_minor,
        recomputed=recomputed,
        text_figures=figures,
    )


def v07(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    found = numerals_outside_placeholders(_text(p))
    return _result(
        "V-07",
        not found,
        "numbers written outside value placeholders" if found else "",
        numerals=found,
    )


def v08(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    key = str(p.params.get("recurring_id") or "")
    for goal in world.goals.values():
        if goal.funded_by and goal.funded_by == key:
            if p.action in ("cancel_recurring", "downgrade_recurring"):
                return _result(
                    "V-08", False, f"it reduces payments into {goal.label}", goal=goal.id
                )
            to = p.params.get("to_date")
            if (
                p.action == "reschedule_transfer"
                and goal.target_date
                and to
                and str(to) > str(goal.target_date)
            ):
                return _result(
                    "V-08", False, f"it delays {goal.label} past its target date", goal=goal.id
                )
    worse = impact.cycles_made_worse()
    if worse:
        return _result(
            "V-08",
            False,
            "it raises the chance of going below the buffer in another pay cycle",
            cycles=[d.isoformat() for d in worse],
        )
    return _result("V-08", True)


def v09(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    target = str(p.params.get("category_key") or p.params.get("recurring_id") or "")
    dup = (p.action, target) in world.active_recommendations
    return _result(
        "V-09", not dup, "the same advice is already active" if dup else "", severity="warn"
    )


def v10(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    text = " ".join(_text(p).lower().split())
    generic = [g for g in GENERIC_PHRASES if g in text]
    specific = bool(re.search(r"\{\{[^}]+\}\}", text)) or any(
        tok in text for tok in _specific_tokens(p, world)
    )
    ok = not generic and specific
    return _result(
        "V-10",
        ok,
        "" if ok else "generic advice that would apply to anyone",
        generic=generic,
        specific=specific,
    )


def _specific_tokens(p: InterventionProposal, world: AdviceWorld) -> list[str]:
    tokens: list[str] = []
    cat = _category(p, world)
    if cat:
        tokens += [w for w in re.split(r"[._]", cat) if len(w) > 3]
    ob = world.obligation(str(p.params.get("recurring_id") or ""))
    if ob:
        tokens += [w for w in re.split(r"\W+", ob.label.lower()) if len(w) > 2]
    label = p.params.get("label")
    if isinstance(label, str):
        tokens.append(label.lower())
    tokens += ["payday", "buffer", "transfer", "bill"]
    return [t for t in tokens if t]


def v14(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    hits = output_screen(
        {"title": p.title, "rationale": p.rationale, "params": p.params},
        locale_pack=world.locale_pack,
        check_numerals=False,
    )
    bad = [v.detail for v in hits if v.kind in ("product_advice", "url")]
    return _result("V-14", not bad, "regulated product or outside link" if bad else "", phrases=bad)


def v15(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    if not world.joint:
        return _result("V-15", True)
    hit = PERSON_ATTRIBUTION.search(_text(p))
    return _result("V-15", hit is None, "attributes joint spending to a person" if hit else "")


def v16(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    cat = _category(p, world) or ""
    bad = p.action in CUT_ACTIONS and cat.startswith(NOT_SPEND)
    return _result("V-16", not bad, f"{cat} is not spending" if bad else "", category=cat)


def v17(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    cat = _category(p, world)
    protected = (
        p.action in CUT_ACTIONS
        and cat in world.protected_categories
        and world.user_requested_category != cat
    )
    return _result(
        "V-17", not protected, f"{cat} is a protected commitment" if protected else "", category=cat
    )


def v18(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    cat = _category(p, world) or ""
    text = _text(p)
    about_betting = cat.startswith("betting") or bool(re.search(r"(?i)\b(bet|betting|gambl)", text))
    if not about_betting:
        return _result("V-18", True)
    if not world.betting_opt_in:
        return _result("V-18", False, "betting advice without the user's opt-in")
    moral = MORALISING.findall(text)
    return _result("V-18", not moral, "moralising wording" if moral else "", words=moral)


def v19(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    unconfirmed = world.extra.get("unconfirmed_inflows") or ()
    if not unconfirmed:
        return _result("V-19", True, "no unconfirmed inflows in this profile")
    # The outcome must not depend on money that may not arrive: the proposal's risk benefit is
    # recomputed by the caller without them (world.extra["risk_without_unconfirmed"]).
    flipped = bool(world.extra.get("outcome_flips_without_unconfirmed"))
    return _result("V-19", not flipped, "depends on money that may not arrive" if flipped else "")


def v20(p: InterventionProposal, world: AdviceWorld, impact: Impact) -> RuleResult:
    text = " ".join(x for x in (p.title, p.rationale, p.claimed_impact_text or "") if x)
    symbols = set(CURRENCY_SYMBOLS.findall(text))
    own = CURRENCY_SYMBOL.get(world.currency)
    other_accounts = [a for a, cur in world.account_currencies.items() if cur != world.currency]
    params = str(p.params)
    mentions_other = any(a in params for a in other_accounts) or any(
        isinstance(v, str) and v.upper() in CURRENCY_SYMBOL and v.upper() != world.currency
        for v in p.params.values()
    )
    mixed = (
        p.currency != world.currency or len(symbols) > 1 or bool(symbols - {own}) or mentions_other
    )
    return _result(
        "V-20",
        not mixed,
        "combines amounts in different currencies" if mixed else "",
        symbols=sorted(symbols),
    )


RULES: tuple[Callable[[InterventionProposal, AdviceWorld, Impact], RuleResult], ...] = (
    v01,
    v02,
    v03,
    v04,
    v05,
    v06,
    v07,
    v08,
    v09,
    v10,
    v14,
    v15,
    v16,
    v17,
    v18,
    v19,
    v20,
)

CRITIQUE = {
    "V-01": "Cite only evidence that exists in this profile: {dangling}.",
    "V-02": "Tie the proposal to a finding or the forecast that triggered it.",
    "V-03": "Target something present in the last 90 days.",
    "V-04": "Keep any cap at or above {min_cap_minor} (no more than 40% below the usual level), "
    "and never cut essentials.",
    "V-05": "Choose an action worth at least £10 a month or 5 points less risk.",
    "V-06": "Set claimed_monthly_impact_minor to the recomputed {recomputed}.",
    "V-07": "Write numbers only as {{{{placeholders}}}}; found {numerals}.",
    "V-08": "Don't move the problem into another pay cycle or delay a goal.",
    "V-09": "Don't repeat advice that is already active.",
    "V-10": "Name the specific merchant, category or date; avoid generic advice.",
    "V-14": "No products, investments, credit or outside links.",
    "V-15": "Frame joint spending as the household's, never a person's.",
    "V-16": "Only target real spending, never income, refunds or transfers.",
    "V-17": "Don't cut {category}: it is a protected commitment.",
    "V-18": "Leave betting alone unless the user opted in, and stay neutral.",
    "V-19": "Don't rely on money that may not arrive.",
    "V-20": "Use one currency; never add or compare amounts across currencies.",
}


def critique_for(result: RuleResult) -> str:
    template = CRITIQUE.get(result.rule, result.detail)
    try:
        return template.format(**{k: v for k, v in result.evidence.items()})
    except (KeyError, IndexError, ValueError):
        return template.replace("{", "").replace("}", "")


def deterministic_rules(
    p: InterventionProposal, world: AdviceWorld, impact: Impact
) -> list[RuleResult]:
    return [rule(p, world, impact) for rule in RULES]


__all__ = ["RULES", "TIMING_ACTIONS", "critique_for", "deterministic_rules"]


# Each rule in plain words, as the Evidence drawer lists the Verifier's checks (docs/06 §5).
RULE_NAMES = {
    "V-01": "Its evidence exists in your profile",
    "V-02": "It rests on a finding or the forecast",
    "V-03": "What it changes is in your data",
    "V-04": "It's achievable, not too big a cut",
    "V-05": "It changes enough to matter",
    "V-06": "Its figure matches the engine's",
    "V-07": "Every number traces to a calculation",
    "V-08": "It doesn't set back a goal or your buffer",
    "V-09": "It isn't a repeat of other advice",
    "V-10": "It's specific to your data",
    "V-11": "Its reasoning is grounded in the evidence",
    "V-12": "You could act on it today",
    "V-13": "Its tone is fair and not judgemental",
    "V-14": "It isn't regulated financial advice",
    "V-15": "It's framed for a shared account",
    "V-16": "It counts only your own money",
    "V-17": "It leaves protected savings alone",
    "V-18": "Betting is handled only as you chose",
    "V-19": "It holds without unconfirmed income",
    "V-20": "It doesn't mix currencies",
}
