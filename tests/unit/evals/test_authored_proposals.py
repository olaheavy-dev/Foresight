"""The authored E-VER set is internally honest (evals/datasets/authored/README.md, CHANGELOG
2026-10-13): every evidence ref a good proposal cites truly resolves in its persona's world,
deliberately dangling refs stay dangling, the 14 Oct corrections hold, and every good proposal
passes the deterministic rules as written."""

from __future__ import annotations

from typing import Any

import pytest

from backend.agents.advice.models import InterventionProposal
from backend.agents.advice.verifier import verify
from backend.agents.contracts import EvidenceRef
from evals.advice_world import case_world
from evals.authored import AUTHORED_DIR
from evals.authored import verify as verify_manifest
from evals.common import read_jsonl

ROWS = read_jsonl(AUTHORED_DIR / "bad_proposals.jsonl")
GOOD = [r for r in ROWS if r["expected"] == "APPROVE"]
BY_ID = {r["id"]: r for r in ROWS}


def _refs(row: dict[str, Any]) -> list[EvidenceRef]:
    return [EvidenceRef.model_validate(x) for x in row["proposal"]["trigger_refs"]]


def test_set_is_frozen_and_counted() -> None:
    assert verify_manifest() == []
    assert (len(ROWS), len(GOOD)) == (96, 34)


@pytest.mark.parametrize("row", GOOD, ids=lambda r: r["id"])
def test_every_good_ref_resolves(row: dict[str, Any]) -> None:
    world = case_world(row)
    assert all(world.resolve(ref) for ref in _refs(row))


def test_added_finding_refs_resolve_to_detector_spikes() -> None:
    added = {f"GP-0{n:02d}": "food.eating_out" for n in range(8, 13)}
    for case_id, category in added.items():
        row = BY_ID[case_id]
        fid = f"fnd:category_spike:{category}"
        assert fid in [ref.id for ref in _refs(row)]
        assert case_world(row).resolve(EvidenceRef(kind="finding", id=fid, role="trigger"))


def test_removed_taxi_proposals_stay_removed_and_their_evidence_is_gone() -> None:
    """GP-017–GP-020 cited a P1 taxi spike that is not a planted anomaly; with the
    regular-behaviour rule (docs/07 §6.6) the detector no longer reports it (CHANGELOG 13 Oct)."""
    assert not {"GP-017", "GP-018", "GP-019", "GP-020"} & set(BY_ID)
    taxi = EvidenceRef(kind="finding", id="fnd:category_spike:transport.taxi", role="trigger")
    assert not case_world(BY_ID["GP-008"]).resolve(taxi)


def test_dangling_evidence_cases_still_dangle() -> None:
    for row in ROWS:
        if row["defect"] == "dangling_evidence":
            world = case_world(row)
            assert not all(world.resolve(ref) for ref in _refs(row)), row["id"]


@pytest.mark.parametrize("row", GOOD, ids=lambda r: r["id"])
def test_good_proposals_pass_every_deterministic_rule(row: dict[str, Any]) -> None:
    p = InterventionProposal.model_validate(row["proposal"])
    v = verify(p, case_world(row), round=1, use_judge=False).verification
    assert v.verdict == "APPROVE", v.failed_rules


def test_relabelled_timing_moves_fail_materiality() -> None:
    for case_id in ("GP-039", "GP-040"):
        row = BY_ID[case_id]
        assert (row["expected"], row["defect"]) == ("REJECT", "immaterial_timing")
        p = InterventionProposal.model_validate(row["proposal"])
        v = verify(p, case_world(row), round=1, use_judge=False).verification
        assert "V-05" in v.failed_rules
