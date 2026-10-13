"""Typed contracts of the core loop (docs/06 §4.4 Advisor, §4.5 Verifier).

The Advisor's model output is `AdvisorOutput`; every proposal must carry the mandatory
`claimed_monthly_impact_minor` (rev 4.3) so V-06 can check it against the recomputed impact. Impact
figures shown to the user always come from `recompute_impact`, never from the model.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.agents.contracts import EvidenceRef

Action = Literal[
    "cap_category",
    "cancel_recurring",
    "downgrade_recurring",
    "defer_purchase",
    "move_purchase_date",
    "set_aside_amount",
    "reschedule_transfer",
    "build_buffer",
]
Direction = Literal["improves_buffer", "improves_goal", "reduces_risk"]


class InterventionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(max_length=64)
    action: Action
    currency: str = Field(min_length=3, max_length=3)
    params: dict[str, Any]
    title: str = Field(max_length=80)
    rationale: str = Field(max_length=300)
    trigger_refs: list[EvidenceRef] = Field(min_length=1)
    expected_direction: Direction
    claimed_monthly_impact_minor: int
    claimed_impact_text: str | None = None


class AdvisorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposals: list[InterventionProposal] = Field(max_length=3)
    critique_addressed: list[str] | None = None


class RuleResult(BaseModel):
    rule_id: str  # "V-04@1"
    passed: bool
    severity: Literal["block", "warn"] = "block"
    kind: Literal["deterministic", "judge"] = "deterministic"
    detail: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)

    @property
    def rule(self) -> str:
        return self.rule_id.split("@", 1)[0]


class JudgeCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: Literal["V-11", "V-12", "V-13", "V-14", "V-15", "V-18"]
    passed: bool
    reason: str = Field(max_length=240)


class JudgeOutput(BaseModel):
    """The LLM judge's verdict for one proposal: pass/fail per criterion, one-line reasons."""

    model_config = ConfigDict(extra="forbid")

    criteria: list[JudgeCriterion] = Field(min_length=1, max_length=6)


class Verification(BaseModel):
    proposal_id: str
    round: int
    deterministic: list[RuleResult]
    judge: list[RuleResult] | None = None  # only when every block-severity rule passed
    verdict: Literal["APPROVE", "REJECT", "WITHDRAW"]
    critique: list[str] = Field(default_factory=list)

    @property
    def failed_rules(self) -> list[str]:
        return [r.rule for r in [*self.deterministic, *(self.judge or [])] if not r.passed]
