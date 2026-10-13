"""Labelled stand-ins for single model roles in eval runs that need persisted agent output.

`StubMesh` wraps the real eval Mesh client (cassette replay) and scripts only the roles it is asked
to: the Advisor (`advisor_mode`) and/or the Verifier's judge (`judge_pass`). Every scripted call's
model name is `stub/<role>`, so the AgentStep rows say plainly which answers were scripted.
Everything else (the deterministic Verifier rules, impact recomputation, simulation, persistence)
is the product's own code.
"""

from __future__ import annotations

import json
from typing import Any

from backend.agents.advice.models import AdvisorOutput, JudgeOutput
from backend.mesh.mesh_client import MeshResult, StructuredResult, Usage

JUDGE_RULES = ("V-11", "V-12", "V-13", "V-14")


def _result(role: str, tier: str, value: Any) -> StructuredResult[Any]:
    call = MeshResult(
        text=value.model_dump_json(),
        model=f"stub/{role}",
        response_id=f"stub-{role}",
        usage=Usage(0, 0, 0),
        latency_ms=0,
        used_fallback=False,
        tier=tier,
    )
    return StructuredResult(
        value=value, result=call, strategy="stub", repaired=False, calls=(call,)
    )


def cap_proposal(data: dict[str, Any], category: str, share: float, pid: str) -> dict[str, Any]:
    """A cap on `category` at `share` of its usual (3 × 30-day median) level, citing the baseline
    forecast and, when the profile has one, the stored finding about that category."""
    row = next(r for r in data["spending"] if r["category_key"] == category)
    cap = int(row["median_3x30_minor"] * share)
    refs = [{"kind": "forecast", "id": data["forecast"]["id"], "role": "trigger"}]
    refs += [
        {"kind": "finding", "id": f["id"], "role": "trigger"}
        for f in data.get("findings", [])
        if category in json.dumps(f.get("about"))
    ][:1]
    return {
        "proposal_id": pid,
        "action": "cap_category",
        "currency": data["currency"],
        "params": {"category_key": category, "monthly_cap_minor": cap},
        "title": "Keep this category under {{cap}} a month",
        "rationale": "Spending here is above its usual level before payday; a cap of {{cap}} a "
        "month keeps the lowest balance nearer your buffer.",
        "trigger_refs": refs,
        "expected_direction": "improves_buffer",
        "claimed_monthly_impact_minor": max(0, row["last_30d_minor"] - cap),
    }


class StubMesh:
    """`advisor_mode`: None (real Advisor) | "feasible" | "flawed_once" | "flawed_always".
    `judge_pass`: None (real judge) | True (every judge criterion passes)."""

    def __init__(
        self,
        inner: Any,
        *,
        advisor_mode: str | None = None,
        judge_pass: bool | None = None,
        categories: tuple[str, ...] = ("food.delivery",),
    ) -> None:
        self._inner = inner
        self._advisor = advisor_mode
        self._judge = judge_pass
        self._categories = categories
        self.advisor_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def structured(self, **kwargs: Any) -> Any:
        name = kwargs.get("name")
        if name == "advisor" and self._advisor:
            return self._advise(kwargs)
        if name == "verifier_judge" and self._judge is not None:
            criteria = [
                {"rule": r, "passed": bool(self._judge), "reason": "scripted judge"}
                for r in JUDGE_RULES
            ]
            return _result("judge", "verifier", JudgeOutput.model_validate({"criteria": criteria}))
        return self._inner.structured(**kwargs)

    def _advise(self, kwargs: dict[str, Any]) -> Any:
        self.advisor_calls += 1
        data = json.loads(kwargs["messages"][-1]["content"])["data"]
        flawed = self._advisor == "flawed_always" or (
            self._advisor == "flawed_once" and self.advisor_calls == 1
        )
        present = {r["category_key"] for r in data["spending"]}
        proposals = [
            cap_proposal(data, cat, 0.2 if flawed else 0.8, f"prp_{i + 1}")
            for i, cat in enumerate(c for c in self._categories if c in present)
        ]
        return _result(
            "advisor", "reasoning", AdvisorOutput.model_validate({"proposals": proposals})
        )


__all__ = ["StubMesh", "cap_proposal"]
