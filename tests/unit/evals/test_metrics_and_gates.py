"""Metric functions on tiny inputs, and the gate rule (a null target is never met)."""

from __future__ import annotations

import pytest

from evals.gates import ALL_SUITES, gate, gates
from evals.metrics import (
    accuracy,
    coverage_at,
    interval_coverage,
    macro_f1,
    mae,
    per_class_f1,
    weighted_f1,
    wilson,
)
from evals.suites import target


def test_accuracy() -> None:
    assert accuracy(["a", "b", "c", "a"], ["a", "b", "x", "x"]) == 0.5
    assert accuracy([], []) is None
    with pytest.raises(ValueError, match="length"):
        accuracy(["a"], [])


def test_macro_f1_averages_over_gold_classes() -> None:
    gold = ["a", "a", "b", "b"]
    pred = ["a", "a", "a", "b"]
    # a: P 2/3, R 1 → F1 0.8; b: P 1, R 0.5 → F1 2/3
    assert macro_f1(gold, pred) == pytest.approx((0.8 + 2 / 3) / 2)
    assert weighted_f1(gold, pred) == pytest.approx((0.8 * 2 + 2 / 3 * 2) / 4)
    # a predicted-only class gets no F1 row of its own
    assert set(per_class_f1(["a"], ["z"])) == {"a"}
    assert macro_f1(["a"], ["z"]) == 0.0


def test_mae() -> None:
    assert mae([1, 2, 3], [1, 4, 0]) == pytest.approx(5 / 3)
    assert mae([], []) is None


def test_interval_coverage_is_inclusive() -> None:
    assert interval_coverage([0, 0, 0, 0], [10, 10, 10, 10], [0, 10, 11, -1]) == 0.5
    assert interval_coverage([], [], []) is None


def test_coverage_and_selective_accuracy() -> None:
    cov, sel = coverage_at(["a", "b", "c", "d"], ["a", "x", "c", "d"], [0.9, 0.9, 0.5, 0.2], 0.85)
    assert cov == 0.5
    assert sel == 0.5


def test_wilson_interval_contains_the_proportion() -> None:
    lo, hi = wilson(17, 20) or (0.0, 0.0)
    assert lo < 0.85 < hi
    assert wilson(0, 0) is None


def test_null_target_is_never_met() -> None:
    assert target("x", "x", None, ">=", 0.9, "d")["met"] is None
    assert target("x", "x", 0.9, ">=", 0.9, "d")["met"] is True
    assert target("x", "x", 0.71, "range", (0.72, 0.88), "d")["met"] is False


def test_gate_rules() -> None:
    measured_fail = {"targets": [target("t1", "t", 0.5, ">=", 0.9, "d")], "error": None}
    only_null = {"targets": [target("t1", "t", None, ">=", 0.9, "d")], "error": None}
    later_stage = {"targets": [target("t1", "t", 0.1, ">=", 0.9, "d", stage1=False)], "error": None}
    assert gate(measured_fail)["status"] == "fail"
    assert gate(measured_fail)["failed"] == ["t1"]
    assert gate(only_null) == {
        "status": "pass",
        "rule": "ran without errors",
        "failed": [],
        "unmeasured": ["t1"],
    }
    # Since Stage 2 every measured target gates, whatever stage it was written for.
    assert gate(later_stage)["status"] == "fail"
    opted_out = {
        "targets": [{**target("t1", "t", 0.1, ">=", 0.9, "d"), "gated": False}],
        "error": None,
    }
    assert gate(opted_out)["status"] == "pass"
    assert gate({"targets": [], "error": "boom"})["status"] == "fail"
    assert gate(None)["status"] == "fail"


def test_gates_cover_every_suite_id_and_unrun_suites_fail() -> None:
    gate_map, _ = gates({"E-CAT": {"targets": [], "error": None}})
    assert set(gate_map) == set(ALL_SUITES)
    assert gate_map["E-CAT"] == "pass"
    assert gate_map["E-VER"] == "fail"
