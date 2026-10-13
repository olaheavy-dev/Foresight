"""The §16 regression gate: degradations beyond tolerance fail; a re-baseline needs a changelog
line; a deliberately degraded categoriser rule makes the gate fail."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.finance_core.types import Categorisation
from evals import common
from evals.regression import changelog_problem, compare, main
from evals.run import build_summary, run_suite
from evals.suites import categorisation


def summary(
    *,
    acc: float = 0.84,
    f1: float = 0.73,
    mae30: float = 600.0,
    cov: float = 0.70,
    corrupt: float = 0.85,
    run_id: str = "evalrun_base",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "fast": False,
        "suites_run": ["E-CAT", "E-FC", "E-ING"],
        "gates": {},
        "errors": {},
        "targets": {"E-LOC": [{"id": "E-LOC-1", "met": True}]},
        "suites": {
            "categorisation": {"arms": {"rules_only": {"accuracy": acc, "macro_f1": f1}}},
            "ingestion": {
                "csv_statement": {
                    "reconciliation": {
                        "corrupted_csv": {"detection_rate": corrupt},
                        "clean_tables_rejected": 0,
                    }
                }
            },
            "forecast": {
                "by_horizon": {"30": {"mae_gbp": mae30, "coverage_p10_p90": cov}},
                "mae30_gbp_by_dataset": {"P1-base": mae30},
                "coverage_by_dataset": {"P1-base": cov},
            },
        },
    }


def test_identical_and_improved_runs_pass() -> None:
    base = summary()
    assert compare(summary(), base) == []
    assert compare(summary(acc=0.9, f1=0.8, mae30=500.0, cov=0.79, corrupt=1.0), base) == []


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"acc": 0.825}, "categorisation.accuracy"),
        ({"f1": 0.71}, "categorisation.macro_f1"),
        ({"corrupt": 0.80}, "corrupt_detection_rate"),
        ({"mae30": 631.0}, "MAE(30)"),
        ({"cov": 0.66}, "coverage"),
    ],
)
def test_degradation_beyond_tolerance_fails(change: dict[str, float], fragment: str) -> None:
    problems = compare(summary(**change), summary())  # type: ignore[arg-type]
    assert any(fragment in p for p in problems), problems


def test_degradation_within_tolerance_passes() -> None:
    # accuracy −0.9 pt, MAE +4.9 %, coverage 1 pt further from 0.80
    assert compare(summary(acc=0.831, mae30=629.0, cov=0.69), summary()) == []


def test_loc_check_dropping_fails() -> None:
    latest = summary()
    latest["targets"]["E-LOC"][0]["met"] = False
    assert any("E-LOC-1" in p for p in compare(latest, summary()))


def test_rebaseline_needs_a_changelog_line(tmp_path: Path) -> None:
    import json

    degraded = summary(acc=0.80, run_id="evalrun_tradeoff")
    base_path, latest_path = tmp_path / "baseline.json", tmp_path / "latest.json"
    changelog = tmp_path / "CHANGELOG.md"
    base_path.write_text(json.dumps(summary()))
    latest_path.write_text(json.dumps(degraded))
    changelog.write_text("- evalrun_base: first accepted run\n")
    args = [
        "--latest",
        str(latest_path),
        "--baseline",
        str(base_path),
        "--changelog",
        str(changelog),
    ]
    assert main(args) == 1  # degraded beyond tolerance

    base_path.write_text(json.dumps(degraded))  # accept the trade-off …
    assert main(args) == 1  # … but without saying why, it still fails
    assert changelog_problem(degraded, changelog) is not None

    changelog.write_text(changelog.read_text() + "- evalrun_tradeoff: accepted because …\n")
    assert main(args) == 0


def test_degraded_categoriser_rule_fails_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    def run_cat() -> dict[str, Any]:
        result = run_suite(categorisation, fast=True)
        return build_summary(
            {"E-CAT": result},
            fast=True,
            sha="0" * 40,
            dirty=False,
            now=datetime(2026, 10, 13, tzinfo=timezone.utc),
        )

    baseline = run_cat()
    assert compare(copy.deepcopy(baseline), baseline) == []

    real = common.categorise  # type: ignore[attr-defined]

    def degraded(txn: Any, pack: Any, ctx: Any = None) -> Categorisation:
        c = real(txn, pack, ctx)
        if c.category_key.startswith("groceries"):  # a broken grocery rule
            return Categorisation(c.transaction_id, "uncategorised", c.flow_kind, c.method, 0.3)
        return c

    monkeypatch.setattr(common, "categorise", degraded)
    problems = compare(run_cat(), baseline)
    assert any("categorisation.accuracy" in p for p in problems), problems
