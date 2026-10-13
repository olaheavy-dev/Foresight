"""The README results block is generated from latest.json; nulls print — and are never ✓."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.render_results import END, START, main, render, update

SUMMARY = {
    "run_id": "evalrun_x",
    "git_sha": "abcdef0123",
    "timestamp_utc": "2026-10-13T08:00:00Z",
    "mode": "deterministic",
    "engine_version": "fc-1.0.0",
    "generator_version": "gen-1.0.0",
    "seeds": [1729],
    "suites_run": ["E-CAT", "E-FC"],
    "gate_detail": {
        "E-CAT": {"status": "pass", "rule": "ran without errors", "failed": []},
        "E-FC": {"status": "fail", "rule": "docs/09 targets", "failed": ["FC-coverage-P1"]},
        "E-VER": {"status": "fail", "rule": "not run", "failed": []},
    },
    "targets": {
        "E-FC": [
            {
                "id": "FC-skill-B1",
                "label": "Skill",
                "dataset": "P1",
                "value": 0.5,
                "target": ">= 0.2",
                "met": True,
                "stage1": True,
            },
            {
                "id": "FC-coverage-P1",
                "label": "Coverage",
                "dataset": "P1",
                "value": 0.5,
                "target": "0.72–0.88",
                "met": False,
                "stage1": True,
            },
        ]
    },
    "suites": {
        "categorisation": {"arms": {"rules_only": {"accuracy": 0.8, "macro_f1": None, "n": 10}}},
        "forecast": {
            "by_horizon": {
                "30": {"mae_gbp": 12.5, "best_baseline": "B0", "best_baseline_mae_gbp": 20.0}
            },
            "coverage_by_dataset": {"P1-base": 0.5},
        },
    },
}


def test_render_headline_order_and_nulls() -> None:
    block = render(SUMMARY)
    assert block.startswith(START)
    assert block.endswith(END)
    cat, fc = block.index("| Categorisation |"), block.index("| Forecast | MAE")
    assert cat < fc < block.index("| Reconciliation |")
    assert "0.800 · —" in block  # macro-F1 not measured → —
    assert "B0-flat £20.00" in block
    assert "| Verifier | Bad proposals caught | — | — |" in block
    assert "FC-coverage-P1: Coverage = 0.500" in block
    assert "Not run yet: E-VER." in block


def test_check_mode_detects_drift(tmp_path: Path) -> None:
    import json

    results = tmp_path / "latest.json"
    readme = tmp_path / "README.md"
    results.write_text(json.dumps(SUMMARY))
    readme.write_text(f"# x\n\n{START}\nstale\n{END}\n\nmore\n")
    core = tmp_path / "core-metrics.json"
    args = ["--results", str(results), "--readme", str(readme), "--core-json", str(core)]
    assert main([*args, "--check"]) == 1
    assert main(args) == 0
    assert main([*args, "--check"]) == 0
    assert readme.read_text().endswith(f"{END}\n\nmore\n")
    assert json.loads(core.read_text())["run_id"] == "evalrun_x"
    core.write_text("{}")
    assert main([*args, "--check"]) == 1  # /quality's copy drifted


def test_core_metrics_come_first_with_tier_gates() -> None:
    summary = {
        **SUMMARY,
        "gate_detail": {**SUMMARY["gate_detail"], "E-EFF": {"status": "fail"},
                        "E-VER": {"status": "pass"}},
        "targets": {"E-EFF": [{"id": "EFF-7", "label": "Advice p95", "value": 61.0,
                               "target": "<= 60.0", "met": False}]},
        "suites": {**SUMMARY["suites"], "efficiency": {
            "by_tier": {"verifier": {"models": ["anthropic/claude-sonnet-5.5"],
                                     "accuracy_gates": ["E-VER"], "cost_per_answer_usd": 0.004,
                                     "call_latency_p50_s": 4.8, "call_latency_p95_s": 7.0}},
            "by_answer_type": {"advice": {"answers": 9, "cost_mean_usd": 0.02,
                                          "cost_p95_usd": 0.03, "latency_p50_s": 31.0,
                                          "latency_p95_s": 61.0}},
        }},
    }  # fmt: skip
    block = render(summary)
    assert block.index("**Core metrics: cost · accuracy · latency**") < block.index("**Headline**")
    assert (
        "| verifier | `anthropic/claude-sonnet-5.5` | E-VER ✓ | $0.0040 | 4.8 s / 7.0 s |" in block
    )
    assert "| Advice answers | 9 | $0.0200 · $0.0300 | 31.0 s · 61.0 s |" in block
    assert "EFF-7 <= 60.0 ✗" in block


def test_missing_markers_raise() -> None:
    with pytest.raises(ValueError, match="RESULTS markers"):
        update("no markers", render(SUMMARY))
