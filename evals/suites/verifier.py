"""E-VER: Verifier efficacy (docs/09 §9.3) on the 62 bad + 34 good authored proposals.

Each proposal is injected at the Verifier with its persona's world (`evals.advice_world`):

- **deterministic arm**: V-01…V-20 code checks only (no model; always measured);
- **full arm**: code checks, then the LLM judge on the `verifier` tier (replay by default);
- **loop**: every rejected proposal goes back to the Advisor with the critique for up to two
  revisions (docs/06 W4), and each revision is verified again. This gives revision success for
  revisable defects and withdraw correctness for unrevisable ones.

Catch rate counts a bad proposal as caught when it is not approved. Attribution says which check
fired: a deterministic rule, or only the judge.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from backend.agents.advice.advisor import advise
from backend.agents.advice.models import InterventionProposal, Verification
from backend.agents.advice.verifier import verify
from backend.mesh.mesh_client import MeshCallError, MeshClient
from evals.advice_world import BASELINE, case_world
from evals.authored import AUTHORED_DIR
from evals.common import read_jsonl
from evals.mesh_eval import NOT_RECORDED, eval_mesh, eval_mode
from evals.metrics import r4
from evals.suites import Target, target

SUITE_ID = "E-VER"
NAME = "verifier"
CASES = AUTHORED_DIR / "bad_proposals.jsonl"
FAST_CASES = 20
MAX_REVISIONS = 2
DETERMINISTIC_DEFECTS = frozenset(
    {
        "dangling_evidence",
        "impact_mismatch",
        "infeasible_cut",
        "cut_commitment",
        "nonexistent_target",
        "cross_currency_arithmetic",
        "immaterial_timing",
    }
)
# A defect the Advisor can fix by changing the proposal; the others should end withdrawn (or as
# a different, valid proposal that no longer has the defect).
REVISABLE = frozenset(
    {
        "dangling_evidence",
        "wrong_evidence",
        "impact_mismatch",
        "infeasible_cut",
        "generic_advice",
        "immaterial_timing",
        "goal_contradiction",
    }
)


class NotRecorded(Exception):
    """A model exchange this run needs was never recorded."""


@dataclass
class CaseRun:
    case: dict[str, Any]
    deterministic: Verification
    full: Verification | None = None
    rounds: list[Verification] = field(default_factory=list)  # the loop, round 1..3
    final: InterventionProposal | None = None  # last proposal verified in the loop
    error: str | None = None

    @property
    def expected_reject(self) -> bool:
        return bool(self.case["expected"] == "REJECT")


def _proposal(case: dict[str, Any]) -> InterventionProposal:
    return InterventionProposal.model_validate(case["proposal"])


def _revise(case: dict[str, Any], mesh: MeshClient, run: CaseRun, first: Verification) -> None:
    world = case_world(case)
    proposal = _proposal(case)
    verdict = first
    for _round in range(MAX_REVISIONS):
        if verdict.verdict != "REJECT":
            break
        revision = [{"proposal": proposal.model_dump(), "critique": verdict.critique}]
        advice = advise(world, mesh, forecast_id=BASELINE, question=None, revision=revision)
        if not advice.proposals:
            break
        same = [p for p in advice.proposals if p.proposal_id == proposal.proposal_id]
        proposal = (same or advice.proposals)[0]
        verdict = verify(
            proposal,
            world,
            round=len(run.rounds) + 1,
            mesh=mesh,
            impact=advice.impacts.get(proposal.proposal_id),
        ).verification
        run.rounds.append(verdict)
    run.final = proposal


@lru_cache(maxsize=2)
def run_cases(fast: bool, with_models: bool) -> tuple[list[CaseRun], int, str]:
    """All case runs (cached for E-GRD in the same process), the count of exchanges missing from
    the cassettes, and the mode."""
    cases = read_jsonl(CASES)
    if fast:
        cases = cases[: FAST_CASES // 2] + cases[-FAST_CASES // 2 :]
    mesh = eval_mesh() if with_models else None
    missing = 0
    runs: list[CaseRun] = []
    for case in cases:
        world = case_world(case)
        p = _proposal(case)
        det = verify(p, world, round=1, use_judge=False).verification
        run = CaseRun(case, det)
        runs.append(run)
        if mesh is None:
            continue
        try:
            full = verify(p, world, round=1, mesh=mesh).verification
            run.full = full
            run.rounds.append(full)
            _revise(case, mesh, run, full)
        except NOT_RECORDED:
            missing += 1
            run.full = None
            run.rounds = []
        except MeshCallError as exc:
            run.error = type(exc).__name__
    return runs, missing, eval_mode()


def _rate(n: int, d: int) -> float | None:
    return r4(n / d) if d else None


def arm_metrics(runs: list[CaseRun], arm: str) -> dict[str, Any]:
    def verdict(r: CaseRun) -> Verification | None:
        return r.deterministic if arm == "deterministic" else r.full

    usable = [r for r in runs if verdict(r) is not None]
    bad = [r for r in usable if r.expected_reject]
    good = [r for r in usable if not r.expected_reject]
    caught = [r for r in bad if verdict(r).verdict != "APPROVE"]  # type: ignore[union-attr]
    false_rej = [r for r in good if verdict(r).verdict != "APPROVE"]  # type: ignore[union-attr]
    by_defect: dict[str, list[bool]] = defaultdict(list)
    attribution: Counter[str] = Counter()
    rule_hit: list[bool] = []
    for r in bad:
        v = verdict(r)
        assert v is not None
        by_defect[str(r.case["defect"])].append(v.verdict != "APPROVE")
        det_failed = [x.rule for x in v.deterministic if not x.passed]
        judge_failed = [x.rule for x in v.judge or [] if not x.passed]
        attribution["deterministic" if det_failed else "judge" if judge_failed else "missed"] += 1
        rule_hit.append(bool(set(r.case["expected_rules"]) & set(det_failed + judge_failed)))
    det_types = [r for r in bad if r.case["defect"] in DETERMINISTIC_DEFECTS]
    return {
        "bad": len(bad),
        "good": len(good),
        "catch_rate": _rate(len(caught), len(bad)),
        "catch_rate_deterministic_types": _rate(
            sum(verdict(r).verdict != "APPROVE" for r in det_types),  # type: ignore[union-attr]
            len(det_types),
        ),
        "false_rejection_rate": _rate(len(false_rej), len(good)),
        "expected_rule_fired": _rate(sum(rule_hit), len(rule_hit)),
        "by_defect": {k: _rate(sum(v), len(v)) for k, v in sorted(by_defect.items())},
        "attribution": dict(attribution),
        "missed": [r.case["id"] for r in bad if verdict(r).verdict == "APPROVE"],  # type: ignore[union-attr]
        "false_rejections": [
            {"id": r.case["id"], "rules": verdict(r).failed_rules}  # type: ignore[union-attr]
            for r in false_rej
        ],
    }


def loop_metrics(runs: list[CaseRun]) -> dict[str, Any]:
    looped = [r for r in runs if r.rounds and r.rounds[0].verdict == "REJECT"]
    revisable = [r for r in looped if r.case.get("defect") in REVISABLE]
    unrevisable = [r for r in looped if r.case.get("defect") and r.case["defect"] not in REVISABLE]
    approved = [r for r in revisable if r.rounds[-1].verdict == "APPROVE"]
    revisions: Counter[str] = Counter()
    for r in looped:
        last = r.rounds[-1].verdict
        revisions["withdrawn" if last != "APPROVE" else f"{len(r.rounds) - 1}_revision(s)"] += 1

    def safe_end(r: CaseRun) -> bool:
        # Unrevisable: withdrawn, or an approved proposal that no longer has the defect (the
        # final proposal passed every check, so the defect cannot remain).
        return r.rounds[-1].verdict != "APPROVE" or not (
            set(r.case["expected_rules"]) & set(r.rounds[-1].failed_rules)
        )

    return {
        "rejected_in_round_1": len(looped),
        "revision_success": _rate(len(approved), len(revisable)),
        "revisable": len(revisable),
        "withdraw_correctness": _rate(sum(safe_end(r) for r in unrevisable), len(unrevisable)),
        "unrevisable": len(unrevisable),
        "outcomes": dict(revisions),
    }


def run(fast: bool = False) -> dict[str, Any]:
    runs, missing, mode = run_cases(fast, True)
    det = arm_metrics(runs, "deterministic")
    full_measured = missing == 0 and all(r.full is not None for r in runs)
    full = arm_metrics(runs, "full") if full_measured else None
    loop = loop_metrics(runs) if full_measured else None
    notes = [f"mode: {mode}"]
    if missing:
        notes.append(
            f"{missing} cases have no recorded judge/Advisor exchange: full arm not measured"
        )
    errors = [r.case["id"] for r in runs if r.error]
    if errors:
        notes.append(f"Mesh errors on {len(errors)} cases: {errors[:10]}")
    headline = full or det
    metrics = {
        "cases": len(runs),
        "deterministic_arm": det,
        "full_arm": full,
        "loop": loop,
        "headline_arm": "full" if full else "deterministic",
    }
    targets: list[Target] = [
        target(
            "VER-catch",
            "Bad proposals caught",
            full["catch_rate"] if full else None,
            ">=",
            0.95,
            f"{len([r for r in runs if r.expected_reject])} bad",
        ),
        target(
            "VER-catch-det",
            "Caught, deterministic defect types",
            headline["catch_rate_deterministic_types"],
            "==",
            1.0,
            "deterministic defect types",
        ),
        target(
            "VER-false-rej",
            "Good proposals falsely rejected",
            full["false_rejection_rate"] if full else None,
            "<=",
            0.10,
            f"{len([r for r in runs if not r.expected_reject])} good",
        ),
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
