"""The Verifier (docs/06 §4.5, §5): deterministic rules first, then the LLM judge.

The judge runs on the `verifier` tier, a different provider from the Advisor's `reasoning` tier
(docs/06 §13), and only when every block-severity deterministic rule passed. A proposal is
APPROVEd only if every block rule (deterministic and judge) passes. If the judge can't be reached,
the proposal couldn't be checked, so it is WITHDRAWn rather than shown (docs/00 §13).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.agents.advice.impact import Impact, recompute_impact
from backend.agents.advice.models import (
    InterventionProposal,
    JudgeOutput,
    RuleResult,
    Verification,
)
from backend.agents.advice.rules import VERSION, critique_for, deterministic_rules
from backend.agents.advice.world import AdviceWorld
from backend.agents.cache import prompt_version
from backend.agents.prompting import system_prompt
from backend.mesh.mesh_client import MeshCallError, MeshClient, MeshResult, ModelTier

JUDGE_PROMPT = "verifier_judge"
ALWAYS_JUDGED = ("V-11", "V-12", "V-13", "V-14")


@dataclass
class VerifyOutcome:
    verification: Verification
    impact: Impact
    llm: list[MeshResult] = field(default_factory=list)
    prompt_version: str | None = None


def _judge_messages(
    p: InterventionProposal, world: AdviceWorld, passed: list[RuleResult]
) -> list[dict[str, str]]:
    about_betting = "betting" in json.dumps(p.params).lower() or "bet" in p.rationale.lower()
    data = {
        "proposal": {
            "title": p.title,
            "rationale": p.rationale,
            "action": p.action,
            "params": p.params,
            "cited": [r.model_dump() for r in p.trigger_refs],
        },
        "evidence": world.evidence_summaries(p.trigger_refs),
        "deterministic_checks": [r.rule for r in passed if r.passed],
        "context": {
            "joint": world.joint,
            "betting": about_betting,
            "betting_opt_in": world.betting_opt_in,
        },
    }
    return [
        {"role": "system", "content": system_prompt(JUDGE_PROMPT)},
        {"role": "user", "content": json.dumps({"data": data}, ensure_ascii=False, default=str)},
    ]


def _judge_results(out: JudgeOutput) -> list[RuleResult]:
    seen = {c.rule: c for c in out.criteria}
    results = [
        RuleResult(rule_id=f"{rule}@{VERSION}", passed=c.passed, kind="judge", detail=c.reason)
        for rule, c in seen.items()
    ]
    # A criterion the judge must always answer but didn't is not a pass.
    for rule in ALWAYS_JUDGED:
        if rule not in seen:
            results.append(
                RuleResult(
                    rule_id=f"{rule}@{VERSION}",
                    passed=False,
                    kind="judge",
                    detail="the judge did not answer this criterion",
                )
            )
    return results


def verify(
    p: InterventionProposal,
    world: AdviceWorld,
    *,
    round: int,
    mesh: MeshClient | None = None,
    use_judge: bool = True,
    before_llm: Callable[[], None] | None = None,
    impact: Impact | None = None,
) -> VerifyOutcome:
    impact = impact or recompute_impact(p, world)
    det = deterministic_rules(p, world, impact)
    blocking = [r for r in det if not r.passed and r.severity == "block"]
    if blocking:
        v = Verification(
            proposal_id=p.proposal_id,
            round=round,
            deterministic=det,
            verdict="REJECT",
            critique=[critique_for(r) for r in blocking],
        )
        return VerifyOutcome(v, impact)
    warn_dup = any(r.rule == "V-09" and not r.passed for r in det)
    if warn_dup:
        v = Verification(
            proposal_id=p.proposal_id,
            round=round,
            deterministic=det,
            verdict="WITHDRAW",
            critique=["the same advice is already active"],
        )
        return VerifyOutcome(v, impact)
    if not use_judge:
        v = Verification(
            proposal_id=p.proposal_id, round=round, deterministic=det, verdict="APPROVE"
        )
        return VerifyOutcome(v, impact)
    if mesh is None:
        raise MeshCallError("the Verifier judge needs a Mesh client")
    if before_llm is not None:
        before_llm()
    try:
        result = mesh.structured(
            tier=ModelTier.VERIFIER,
            messages=_judge_messages(p, world, det),
            output=JudgeOutput,
            name="verifier_judge",
            max_tokens=700,
            locale_pack=world.locale_pack,
        )
    except MeshCallError as exc:
        v = Verification(
            proposal_id=p.proposal_id,
            round=round,
            deterministic=det,
            verdict="WITHDRAW",
            critique=[f"couldn't be checked: {type(exc).__name__}"],
        )
        return VerifyOutcome(v, impact)
    judged = _judge_results(result.value)
    failed = [r for r in judged if not r.passed]
    v = Verification(
        proposal_id=p.proposal_id,
        round=round,
        deterministic=det,
        judge=judged,
        verdict="REJECT" if failed else "APPROVE",
        critique=[f"{r.rule}: {r.detail}" for r in failed],
    )
    return VerifyOutcome(v, impact, list(result.calls), prompt_version(JUDGE_PROMPT))


def verification_record(v: Verification) -> list[dict[str, Any]]:
    """Rule results as stored on `verification_result.rule_results`."""
    return [
        {
            "rule": r.rule_id,
            "passed": r.passed,
            "kind": r.kind,
            "severity": r.severity,
            "reason": r.detail,
            "evidence": r.evidence,
        }
        for r in [*v.deterministic, *(v.judge or [])]
    ]
