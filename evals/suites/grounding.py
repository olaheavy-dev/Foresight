"""E-GRD: grounding of approved recommendations (docs/09 §9.2).

Measured on every recommendation the loop approves in E-VER (the 40 good proposals and every
rejected proposal the Advisor revised into an approved one), using the same run in this process:

- **evidence-ref validity**: every cited ref resolves in the same profile;
- **numeric-claim match**: no number written outside a `{{placeholder}}` (placeholders are filled
  from calculations, so a number the model wrote can't match one);
- **generic-advice rate**: approved advice that names nothing specific, carries no computed impact
  or cites no finding or forecast;
- **commitment respect**: approved cuts to a protected category the user didn't ask about;
- **swap test**: P1's approved advice re-verified against P2's data must fail.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from backend.agents.advice.rules import v10
from backend.agents.advice.verifier import verify
from backend.agents.guard.output import numerals_outside_placeholders
from evals.advice_world import base_world, case_world
from evals.metrics import r4
from evals.suites import Target, target
from evals.suites.verifier import run_cases

SUITE_ID = "E-GRD"
NAME = "grounding"
CUT_ACTIONS = frozenset({"cap_category", "cancel_recurring", "downgrade_recurring"})


def _rate(n: int, d: int) -> float | None:
    return r4(n / d) if d else None


def run(fast: bool = False) -> dict[str, Any]:
    runs, missing, mode = run_cases(fast, True)
    notes = [f"mode: {mode}"]
    if missing or not any(r.rounds for r in runs):
        notes.append("the loop was not run (no recorded model exchanges): not measured")
        empty = {"approved": 0}
        targets = [
            target("GRD-refs", "Evidence refs resolve", None, "==", 1.0, "approved"),
            target("GRD-numbers", "No model-written numbers", None, ">=", 0.98, "approved"),
            target("GRD-generic", "Generic advice among approved", None, "==", 0.0, "approved"),
        ]
        return {"metrics": empty, "targets": targets, "notes": notes}
    approved = [
        r for r in runs if r.rounds and r.rounds[-1].verdict == "APPROVE" and r.final is not None
    ]
    refs_ok = numbers_ok = generic = commitment = 0
    swap_total = swap_failed = 0
    other = {"P1-base": "P2-base", "P2-base": "P1-base"}
    for r in approved:
        p = r.final
        assert p is not None
        world = case_world(r.case)
        refs_ok += all(world.resolve(ref) for ref in p.trigger_refs)
        numbers_ok += not numerals_outside_placeholders(f"{p.title}\n{p.rationale}")
        impact = verify(p, world, round=1, use_judge=False).impact
        specific = v10(p, world, impact).passed
        has_impact = impact.monthly_minor is not None and (
            impact.monthly_minor > 0 or impact.simulated
        )
        cites = any(ref.kind in ("finding", "forecast") for ref in p.trigger_refs)
        generic += not (specific and has_impact and cites)
        cat = str(p.params.get("category_key") or "")
        commitment += (
            p.action in CUT_ACTIONS
            and cat in world.protected_categories
            and world.user_requested_category != cat
        )
        target_ds = other.get(str(r.case["dataset"]))
        if target_ds:
            swapped = dataclasses.replace(base_world(target_ds))
            swap_total += 1
            swap_failed += verify(p, swapped, round=1, use_judge=False).verification.verdict != (
                "APPROVE"
            )
    n = len(approved)
    metrics = {
        "approved": n,
        "evidence_ref_validity": _rate(refs_ok, n),
        "numeric_claim_match": _rate(numbers_ok, n),
        "generic_advice_rate": _rate(generic, n),
        "commitment_cuts_unrequested": commitment,
        "swap_test_fail_rate": _rate(swap_failed, swap_total),
    }
    targets: list[Target] = [
        target(
            "GRD-refs",
            "Evidence refs resolve",
            metrics["evidence_ref_validity"],
            "==",
            1.0,
            "approved",
        ),
        target(
            "GRD-numbers",
            "No model-written numbers",
            metrics["numeric_claim_match"],
            ">=",
            0.98,
            "approved",
        ),
        target(
            "GRD-generic",
            "Generic advice among approved",
            metrics["generic_advice_rate"],
            "==",
            0.0,
            "approved",
        ),
        target(
            "GRD-commitment",
            "Unrequested cuts to protected categories",
            float(commitment),
            "==",
            0.0,
            "approved",
        ),
        target(
            "GRD-swap",
            "Swap test: other persona's advice fails",
            metrics["swap_test_fail_rate"],
            "==",
            1.0,
            "approved",
        ),
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
