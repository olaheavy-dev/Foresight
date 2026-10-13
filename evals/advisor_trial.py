"""Advisor model trial (owner request, 13 Oct 2026): is a cheaper Advisor as good as Sonnet?

Dev material only. The trial cases below are written for this trial, on P1, with cap amounts and
wording that differ from the E-VER test set (evals/datasets/authored/bad_proposals.jsonl), which
is never used to choose. Each case is checked deterministically before any model call: good cases
must pass every code rule, flawed cases must fail the rule their defect names (wrong-evidence cases
are the exception: only the judge can see them).

Arms (the Verifier judge is always a different provider from the Advisor):
  A  Advisor anthropic/claude-sonnet-5.5   judge openai/gpt-6.1-sol   (current)
  B  Advisor google/gemini-3.8-flash       judge openai/gpt-6.1-sol
  C  Advisor openai/gpt-5.6-luna-pro       judge anthropic/claude-sonnet-5.5

Metrics (fixed before running):
  revision success      revisable flawed cases rejected in round 1 that end APPROVE within 2
                        revisions (with the defect gone)
  withdraw correctness  unrevisable flawed cases that end withdrawn, or as a valid different
                        proposal that no longer cuts the protected category
  grounding             E-GRD checks on every approved final proposal: refs resolve, no
                        model-written numbers, not generic, no unrequested protected cuts
  schema repair rate    structured calls that needed the repair retry or failed
  latency p50           per Advisor call
  cost per case         from Mesh-reported usage x catalogue prices

Decision rule (fixed before running): a cheaper arm wins only if its revision success and its
grounding rate are each >= arm A's minus 2 points AND it has no grounding violations; among
winners the cheapest wins; otherwise A stays.

Usage: python -m evals.advisor_trial build|check|run <arm>|report <run_dir>
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.agents.advice.advisor import advise
from backend.agents.advice.models import InterventionProposal, Verification
from backend.agents.advice.rules import v10
from backend.agents.advice.verifier import verify
from backend.agents.guard.output import numerals_outside_placeholders
from backend.mesh import mesh_client as mc
from backend.mesh.prices import cost_estimate
from backend.settings import get_settings
from evals.advice_world import BASELINE, base_world, case_world

ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / "results" / "20261013T2200Z_advisor_model_trial"
CASES_FILE = RUN_DIR / "dev_cases.jsonl"
MAX_REVISIONS = 2
ARMS: dict[str, dict[str, str]] = {
    "A": {"reasoning": "anthropic/claude-sonnet-5.5", "verifier": "openai/gpt-6.1-sol"},
    "B": {"reasoning": "google/gemini-3.8-flash", "verifier": "openai/gpt-6.1-sol"},
    "C": {"reasoning": "openai/gpt-5.6-luna-pro", "verifier": "anthropic/claude-sonnet-5.5"},
}
FINDING = {
    "food.delivery": "fnd:category_spike:food.delivery",
    "food.eating_out": "fnd:category_spike:food.eating_out",
}
REVISABLE = {"impact_mismatch", "infeasible_cut", "dangling_evidence", "generic_advice"}
REVISABLE |= {"wrong_evidence"}


def _cap_case(
    cid: str,
    cat: str,
    cap: int,
    *,
    expected: str,
    defect: str | None = None,
    claimed: int | None = None,
    refs: list[dict[str, str]] | None = None,
    title: str | None = None,
    rationale: str | None = None,
) -> dict[str, Any]:
    world = base_world("P1-base")
    true_impact = max(0, world.last_30d(cat) - cap)
    label = cat.split(".")[-1].replace("_", " ")
    return {
        "id": cid,
        "dataset": "P1-base",
        "as_of": world.as_of.isoformat(),
        "context": {},
        "expected": expected,
        "defect": defect,
        "proposal": {
            "proposal_id": f"prp_{cid.lower().replace('-', '_')}",
            "action": "cap_category",
            "params": {"category_key": cat, "monthly_cap_minor": cap},
            "claimed_monthly_impact_minor": claimed if claimed is not None else true_impact,
            "claimed_impact_text": None,
            "currency": "GBP",
            "expected_direction": "improves_buffer",
            "title": title or f"Hold {label} at {{{{cap}}}} a month until the next payday",
            "rationale": rationale
            or (
                f"Your {label} spending has risen above its usual level; holding it at {{{{cap}}}}"
                " a month eases the low point before payday."
            ),
            "trigger_refs": refs
            if refs is not None
            else [
                {"id": FINDING[cat], "kind": "finding", "role": "trigger"},
                {"id": BASELINE, "kind": "forecast", "role": "trigger"},
            ],
        },
    }


def build_cases() -> list[dict[str, Any]]:
    fc = {"id": BASELINE, "kind": "forecast", "role": "trigger"}

    def ref(rid: str) -> dict[str, str]:
        return {"id": rid, "kind": "finding", "role": "trigger"}

    d, e = "food.delivery", "food.eating_out"
    generic_r = "Try to spend less and cut back where you can so the month is easier."
    return [
        # good: valid caps (cap amounts differ from the test set)
        _cap_case("TR-G1", d, 14000, expected="APPROVE"),
        _cap_case("TR-G2", d, 16500, expected="APPROVE"),
        _cap_case("TR-G3", d, 18000, expected="APPROVE"),
        _cap_case("TR-G4", e, 18000, expected="APPROVE"),
        _cap_case("TR-G5", e, 21000, expected="APPROVE"),
        _cap_case("TR-G6", e, 24000, expected="APPROVE"),
        # flawed, revisable
        _cap_case("TR-B1", d, 15000, expected="REJECT", defect="impact_mismatch", claimed=20000),
        _cap_case("TR-B2", e, 20000, expected="REJECT", defect="impact_mismatch", claimed=25000),
        _cap_case("TR-B3", d, 9000, expected="REJECT", defect="infeasible_cut"),
        _cap_case("TR-B4", e, 12000, expected="REJECT", defect="infeasible_cut"),
        _cap_case(
            "TR-B5",
            d,
            15000,
            expected="REJECT",
            defect="dangling_evidence",
            refs=[ref("fnd:category_spike:food.coffee"), fc],
        ),
        _cap_case(
            "TR-B6",
            e,
            20000,
            expected="REJECT",
            defect="dangling_evidence",
            refs=[ref("fnd:category_spike:entertainment"), fc],
        ),
        _cap_case(
            "TR-B7",
            d,
            15000,
            expected="REJECT",
            defect="generic_advice",
            title="Try to spend less this month",
            rationale=generic_r,
        ),
        _cap_case(
            "TR-B8",
            e,
            20000,
            expected="REJECT",
            defect="generic_advice",
            title="Cut back and save more",
            rationale=generic_r,
        ),
        _cap_case(
            "TR-B9",
            d,
            15000,
            expected="REJECT",
            defect="wrong_evidence",
            refs=[ref("fnd:price_change:rob_spotify"), fc],
        ),
        _cap_case(
            "TR-B10",
            e,
            20000,
            expected="REJECT",
            defect="wrong_evidence",
            refs=[ref("fnd:subscription_overlap:rob_netflix+rob_sky"), fc],
        ),
        # flawed, unrevisable: a cut to a protected commitment the user didn't ask about
        _cap_case(
            "TR-U1",
            "family_support_abroad",
            18000,
            expected="REJECT",
            defect="cut_commitment",
            refs=[fc],
            title="Hold family support at {{cap}} a month",
            rationale="Holding family support at {{cap}} a month eases the low point.",
        ),
        _cap_case(
            "TR-U2",
            "family_support_abroad",
            21000,
            expected="REJECT",
            defect="cut_commitment",
            refs=[fc],
            title="Send {{cap}} home this month instead",
            rationale="Sending {{cap}} home this month keeps the balance above the buffer.",
        ),
    ]


def _proposal(case: dict[str, Any]) -> InterventionProposal:
    return InterventionProposal.model_validate(case["proposal"])


def write_cases() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(c, sort_keys=True, ensure_ascii=False) + "\n" for c in build_cases())
    CASES_FILE.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode()).hexdigest()
    (RUN_DIR / "dev_cases.sha256").write_text(f"{digest}  dev_cases.jsonl\n", encoding="utf-8")
    print(f"wrote {CASES_FILE} ({len(build_cases())} cases) sha256 {digest[:12]}")


def load_cases() -> list[dict[str, Any]]:
    text = CASES_FILE.read_text(encoding="utf-8")
    want = (RUN_DIR / "dev_cases.sha256").read_text(encoding="utf-8").split()[0]
    if hashlib.sha256(text.encode()).hexdigest() != want:
        raise SystemExit("dev_cases.jsonl changed after it was frozen")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def check_cases() -> list[str]:
    """Deterministic pre-check: good cases pass every code rule; flawed ones fail (except
    wrong-evidence, which only the judge can see)."""
    problems = []
    for case in load_cases():
        v = verify(_proposal(case), case_world(case), round=1, use_judge=False).verification
        if case["expected"] == "APPROVE" and v.verdict != "APPROVE":
            problems.append(f"{case['id']}: good case fails code rules: {v.critique}")
        if case["defect"] not in (None, "wrong_evidence") and v.verdict == "APPROVE":
            problems.append(f"{case['id']}: flawed case passes code rules ({case['defect']})")
    return problems


# ---------------------------------------------------------------------------------- running


@dataclass
class Call:
    tier: str
    model: str
    latency_s: float
    tokens_in: int
    tokens_out: int
    cost: float
    repaired: bool
    failed: bool
    fallback: bool = False


@dataclass
class CaseResult:
    case_id: str
    expected: str
    defect: str | None
    rounds: list[str] = field(default_factory=list)  # verdicts
    final: dict[str, Any] | None = None
    final_verdict: str | None = None
    withdrawn: bool = False
    error: str | None = None


CALLS: list[Call] = []


def _instrument() -> None:
    original = mc.MeshClient.structured

    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        tier = str(getattr(kwargs.get("tier"), "value", kwargs.get("tier")))
        t0 = time.monotonic()
        try:
            out = original(self, *args, **kwargs)
        except mc.MeshSchemaError:
            CALLS.append(Call(tier, "?", time.monotonic() - t0, 0, 0, 0.0, True, True, False))
            raise
        dt = time.monotonic() - t0
        for res in out.calls:
            tin = int(res.usage.prompt_tokens or 0)
            tout = int(res.usage.completion_tokens or 0)
            cost = res.cost_estimate
            if cost is None:
                cost = cost_estimate(res.model, tin, tout) or 0.0
            CALLS.append(
                Call(
                    tier,
                    res.model,
                    dt,
                    tin,
                    tout,
                    float(cost),
                    bool(out.repaired),
                    False,
                    bool(res.used_fallback),
                )
            )
        return out

    mc.MeshClient.structured = wrapped  # type: ignore[method-assign]


def _mesh_for(arm: str, mode: str) -> mc.MeshClient:
    models = ARMS[arm]
    os.environ["MESH_MODEL_REASONING"] = models["reasoning"]
    os.environ["MESH_MODEL_REASONING_FALLBACK"] = models["reasoning"]
    os.environ["MESH_MODEL_VERIFIER"] = models["verifier"]
    os.environ["MESH_MODEL_VERIFIER_FALLBACK"] = models["verifier"]
    os.environ["MESH_CASSETTE_MODE"] = mode
    os.environ["MESH_CASSETTE_DIR"] = str(RUN_DIR / "cassettes")
    get_settings.cache_clear()
    return mc.MeshClient(settings=get_settings())


def run_arm(arm: str, mode: str = "record") -> list[CaseResult]:
    _instrument()
    mesh = _mesh_for(arm, mode)
    results: list[CaseResult] = []
    for case in load_cases():
        world = case_world(case)
        proposal = _proposal(case)
        r = CaseResult(case["id"], case["expected"], case["defect"])
        try:
            v: Verification = verify(proposal, world, round=1, mesh=mesh).verification
            r.rounds.append(v.verdict)
            for _ in range(MAX_REVISIONS):
                if v.verdict != "REJECT":
                    break
                revision = [{"proposal": proposal.model_dump(), "critique": v.critique}]
                advice = advise(world, mesh, forecast_id=BASELINE, revision=revision)
                if not advice.proposals:
                    r.withdrawn = True
                    break
                same = [p for p in advice.proposals if p.proposal_id == proposal.proposal_id]
                proposal = (same or advice.proposals)[0]
                v = verify(
                    proposal,
                    world,
                    round=len(r.rounds) + 1,
                    mesh=mesh,
                    impact=advice.impacts.get(proposal.proposal_id),
                ).verification
                r.rounds.append(v.verdict)
            r.final = proposal.model_dump(mode="json")
            r.final_verdict = v.verdict
            if v.verdict == "REJECT":
                r.withdrawn = True
        except mc.MeshCallError as exc:
            r.error = type(exc).__name__
        results.append(r)
        print(f"{arm} {r.case_id}: {r.rounds} withdrawn={r.withdrawn} err={r.error}", flush=True)
    out = RUN_DIR / f"arm_{arm}.json"
    out.write_text(
        json.dumps(
            {
                "arm": arm,
                "models": ARMS[arm],
                "mode": mode,
                "results": [r.__dict__ for r in results],
                "calls": [c.__dict__ for c in CALLS],
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    return results


# ---------------------------------------------------------------------------------- metrics


CUT_ACTIONS = frozenset({"cap_category", "cancel_recurring", "downgrade_recurring"})


def _grounded(final: dict[str, Any], case: dict[str, Any]) -> tuple[bool, list[str]]:
    p = InterventionProposal.model_validate(final)
    world = case_world(case)
    why = []
    if not all(world.resolve(ref) for ref in p.trigger_refs):
        why.append("ref does not resolve")
    if numerals_outside_placeholders(f"{p.title}\n{p.rationale}"):
        why.append("model-written number")
    impact = verify(p, world, round=1, use_judge=False).impact
    has_impact = impact.monthly_minor is not None and (impact.monthly_minor > 0 or impact.simulated)
    cites = any(ref.kind in ("finding", "forecast") for ref in p.trigger_refs)
    if not (v10(p, world, impact).passed and has_impact and cites):
        why.append("generic")
    cat = str(p.params.get("category_key") or "")
    if p.action in CUT_ACTIONS and cat in world.protected_categories:
        why.append("protected cut")
    return not why, why


def metrics(arm_file: Path) -> dict[str, Any]:
    data = json.loads(arm_file.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in load_cases()}
    res = data["results"]
    rev = [r for r in res if r["defect"] in REVISABLE and r["rounds"][:1] == ["REJECT"]]
    rev_ok = [r for r in rev if r["final_verdict"] == "APPROVE"]
    unrev = [r for r in res if r["defect"] == "cut_commitment"]
    unrev_ok = 0
    for r in unrev:
        if r["final_verdict"] != "APPROVE":
            unrev_ok += 1
        elif (
            r["final"] and str(r["final"]["params"].get("category_key")) != "family_support_abroad"
        ):
            unrev_ok += 1
    approved = [r for r in res if r["final_verdict"] == "APPROVE" and r["final"]]
    violations: list[str] = []
    grounded = 0
    for r in approved:
        ok, why = _grounded(r["final"], cases[r["case_id"]])
        grounded += ok
        if not ok:
            violations.append(f"{r['case_id']}: {', '.join(why)}")
    good = [r for r in res if r["expected"] == "APPROVE"]
    calls = data["calls"]
    for c in calls:  # price from the configured model (served names can differ in punctuation)
        model = data["models"].get(c["tier"])
        if model and c["tokens_in"]:
            c["cost"] = cost_estimate(model, c["tokens_in"], c["tokens_out"]) or c["cost"]
    adv = [c for c in calls if c["tier"] == "reasoning"]
    cost = sum(c["cost"] for c in calls)
    return {
        "arm": data["arm"],
        "advisor": data["models"]["reasoning"],
        "judge": data["models"]["verifier"],
        "revisable_rejected_r1": len(rev),
        "revision_success": round(len(rev_ok) / len(rev), 4) if rev else None,
        "withdraw_correctness": round(unrev_ok / len(unrev), 4) if unrev else None,
        "good_approved_r1": sum(r["rounds"][:1] == ["APPROVE"] for r in good),
        "good_total": len(good),
        "approved_final": len(approved),
        "grounding_rate": round(grounded / len(approved), 4) if approved else None,
        "grounding_violations": violations,
        "advisor_calls": len(adv),
        "fallback_calls": sum(bool(c.get("fallback")) for c in calls),
        "repair_or_failure_rate": round(
            sum(c["repaired"] or c["failed"] for c in calls) / len(calls), 4
        )
        if calls
        else None,
        "advisor_latency_p50_s": round(statistics.median(c["latency_s"] for c in adv), 2)
        if adv
        else None,
        "advisor_cost_usd": round(sum(c["cost"] for c in adv), 4),
        "total_cost_usd": round(cost, 4),
        "cost_per_case_usd": round(cost / len(res), 4) if res else None,
        "errors": [f"{r['case_id']}: {r['error']}" for r in res if r["error"]],
    }


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "build":
        write_cases()
        return 0
    if cmd == "check":
        problems = check_cases()
        print("\n".join(problems) or "all dev cases behave as labelled under the code rules")
        return 1 if problems else 0
    if cmd == "run":
        run_arm(argv[2], argv[3] if len(argv) > 3 else "record")
        return 0
    if cmd == "metrics":
        print(json.dumps(metrics(RUN_DIR / f"arm_{argv[2]}.json"), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
