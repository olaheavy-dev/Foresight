"""The headline numbers of a summary.json, in one place for the report, regression gate and the
README renderer. Missing values are None (= not run), never zero."""

from __future__ import annotations

from typing import Any


def dig(data: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def target_met(summary: dict[str, Any], suite_id: str) -> dict[str, bool | None]:
    """target id → met (None = not measured) for one suite."""
    return {str(t["id"]): t.get("met") for t in (summary.get("targets") or {}).get(suite_id, [])}


def headline(summary: dict[str, Any]) -> dict[str, Any]:
    s = summary.get("suites") or {}
    rules = dig(s, "categorisation", "arms", "rules_only") or {}
    corrupt = dig(s, "ingestion", "csv_statement", "reconciliation", "corrupted_csv") or {}
    fc30 = dig(s, "forecast", "by_horizon", "30") or {}
    return {
        "categorisation.accuracy": rules.get("accuracy"),
        "categorisation.macro_f1": rules.get("macro_f1"),
        "categorisation.flow_class_accuracy": rules.get("flow_class_accuracy"),
        "categorisation.n": rules.get("n"),
        "categorisation.majority_accuracy": dig(
            s, "categorisation", "arms", "majority_class", "accuracy"
        ),
        "reconciliation.corrupt_detection_rate": corrupt.get("detection_rate"),
        "reconciliation.corrupt_detected": corrupt.get("detected"),
        "reconciliation.corrupt_total": corrupt.get("total"),
        "reconciliation.clean_tables_rejected": dig(
            s, "ingestion", "csv_statement", "reconciliation", "clean_tables_rejected"
        ),
        "forecast.mae30_gbp": fc30.get("mae_gbp"),
        "forecast.best_baseline_30": fc30.get("best_baseline"),
        "forecast.best_baseline_mae30_gbp": fc30.get("best_baseline_mae_gbp"),
        "forecast.skill_vs_best_30": dig(s, "forecast", "skill_vs", "best_baseline", "30"),
        "forecast.skill_vs_B1_30": dig(s, "forecast", "skill_vs", "B1-repeat30", "30"),
        "forecast.coverage": fc30.get("coverage_p10_p90"),
        "forecast.mae30_gbp_by_dataset": dig(s, "forecast", "mae30_gbp_by_dataset") or {},
        "forecast.coverage_by_dataset": dig(s, "forecast", "coverage_by_dataset") or {},
        "verifier.catch_rate": dig(s, "verifier", "bad_caught_rate"),
        "simulation.pass_rate": dig(s, "simulation", "pass_rate"),
    }
