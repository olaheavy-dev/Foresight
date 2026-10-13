"""The design examples in design/contracts/ against the Pydantic contracts (API-01).

The examples are documentation and are not fixed here. This test pins exactly where each one
departs from docs/08 as implemented, so a fix to an example (or to the models) shows up as a
diff in KNOWN. An empty entry means the example validates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from backend.app.ui_contracts.plan import ResponsePlan
from backend.app.ui_contracts.response import AgentResponse
from backend.app.ui_contracts.validation import (
    check_currency,
    check_plan_text,
    check_skeleton,
    parse_plan,
    parse_response,
    visible_tabs,
)

CONTRACTS = Path(__file__).resolve().parents[3] / "design" / "contracts"
EXAMPLES = sorted(p.stem for p in CONTRACTS.glob("*.json"))

AET_STEP_TIMES = [
    f"blocks.6.AgentExecutionTimeline.steps.{i}.{field}: missing"
    for i in range(6)
    for field in ("duration_ms", "started_at")
]
KNOWN: dict[str, dict[str, list[str]]] = {
    "01-spending-question": {
        "plan": [
            "blocks.2.SpendingBreakdownChart.query.group_by: missing",
            "blocks.4.SpendingBreakdownChart.query.compare_to: literal_error",
            "follow_ups.1: union_tag_invalid",
        ],
        "response": [
            "blocks.2.SpendingBreakdownChart.by_merchant.series.0.counts: extra_forbidden",
            "blocks.2.SpendingBreakdownChart.by_merchant.series.0.tone: missing",
            "blocks.2.SpendingBreakdownChart.by_merchant.series.0.value: missing",
            "blocks.2.SpendingBreakdownChart.by_merchant.series.0.values: extra_forbidden",
            "blocks.2.SpendingBreakdownChart.by_merchant.unit: extra_forbidden",
            "blocks.2.SpendingBreakdownChart.by_merchant.x: extra_forbidden",
            "blocks.3.InterventionCard.title: string_too_long",
            "blocks.3.InterventionCard.verification.label: extra_forbidden",
            "blocks.3.InterventionCard.version_id: missing",
            "blocks.4.SpendingBreakdownChart.over_time.series.0.nature: extra_forbidden",
            "blocks.4.SpendingBreakdownChart.over_time.total: missing",
            "blocks.4.SpendingBreakdownChart.over_time.unit: extra_forbidden",
            "blocks.5.TransactionTable.has_more: missing",
            "blocks.5.TransactionTable.query: missing",
            "follow_ups.1: union_tag_invalid",
        ],
        "plan_text": [
            "blocks.0.text: ['30']",
            "blocks.1.metrics.0.label: ['30']",
            "blocks.1.metrics.0.compare_label: ['3']",
        ],
    },
    "02-holiday-affordability": {
        "plan": [
            "blocks.2.ScenarioComparison.baseline_ref: string_pattern_mismatch",
            "blocks.2.ScenarioComparison.simulation_refs.0: string_pattern_mismatch",
            "blocks.2.ScenarioComparison.simulation_refs.1: string_pattern_mismatch",
            "blocks.4.CashFlowForecastChart.forecast_ref: string_pattern_mismatch",
            "blocks.4.CashFlowForecastChart.resolution: extra_forbidden",
            "blocks.5.ScenarioComparison.baseline_ref: string_pattern_mismatch",
            "blocks.5.ScenarioComparison.emphasis_metric: literal_error",
            "blocks.5.ScenarioComparison.simulation_refs: too_long",
            "follow_ups.0: union_tag_invalid",
        ],
        "response": [
            "blocks.1.FinancialMetricGroup.metrics.0.caption: extra_forbidden",
            "blocks.1.FinancialMetricGroup.metrics.1.caption: extra_forbidden",
            "blocks.1.FinancialMetricGroup.metrics.2.caption: extra_forbidden",
            "blocks.3.InterventionCard.impact.p_breach_window: missing",
            "blocks.3.InterventionCard.verification.label: extra_forbidden",
            "blocks.3.InterventionCard.version_id: missing",
            "blocks.4.CashFlowForecastChart.paydays: extra_forbidden",
            "blocks.4.CashFlowForecastChart.summary: missing",
            "blocks.5.ScenarioComparison.baseline.end: extra_forbidden",
            "blocks.5.ScenarioComparison.baseline.lowest: extra_forbidden",
            "blocks.5.ScenarioComparison.baseline.series: missing",
            "blocks.5.ScenarioComparison.emphasis: extra_forbidden",
            "blocks.5.ScenarioComparison.scenarios: too_long",
            "blocks.6.AgentExecutionTimeline.cost: missing",
            "blocks.6.AgentExecutionTimeline.duration_ms: missing",
            *AET_STEP_TIMES,
            "follow_ups.0: union_tag_invalid",
        ],
        "plan_text": [
            "blocks.0.text: ['27', '6']",
            "blocks.1.metrics.2.label: ['31', '2027']",
        ],
    },
    "03-proactive-risk-alert": {
        "plan": ["blocks.1.CashFlowForecastChart.resolution: extra_forbidden"],
        "response": [
            "blocks.1.CashFlowForecastChart.resolution: literal_error",
            "blocks.1.CashFlowForecastChart.summary: missing",
            "blocks.2.RiskAssessment.risks.0.drivers.0.ref: missing",
            "blocks.3.InterventionCard.title: string_too_long",
            "blocks.3.InterventionCard.verification.label: extra_forbidden",
            "blocks.3.InterventionCard.version_id: missing",
            "blocks.4.AgentExecutionTimeline.cost: missing",
        ],
        "plan_text": ["blocks.0.text: ['£500', '£650']"],
    },
    "04-plan-outlook": {
        "plan": ["follow_ups.0: union_tag_invalid"],
        "response": ["follow_ups.0: union_tag_invalid"],
        "plan_text": ["blocks.0.text: ['31']", "blocks.1.metrics.2.label: ['£1,200', '27']"],
    },
    "05-verification-loop-timeline": {
        "plan": [],
        "response": [
            "blocks.1.AgentExecutionTimeline.cost: missing",
            "blocks.2.EvidencePanel.items.0.provenance: literal_error",
            "blocks.2.EvidencePanel.items.1.provenance: literal_error",
        ],
        "plan_text": [],
    },
    "06-india-spending-question": {
        "plan": [],
        "response": [
            "blocks.2.SpendingBreakdownChart.over_time.series.0.nature: extra_forbidden",
            "blocks.2.SpendingBreakdownChart.over_time.unit: extra_forbidden",
        ],
        "plan_text": [
            "blocks.1.metrics.0.label: ['30']",
            "blocks.1.metrics.0.compare_label: ['3']",
        ],
    },
}


def _load(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS / f"{name}.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _errors(model: type[BaseModel], raw: dict[str, Any]) -> list[str]:
    try:
        model.model_validate(raw)
    except ValidationError as exc:
        return sorted({f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in exc.errors()})
    return []


def test_every_example_is_covered() -> None:
    assert EXAMPLES == sorted(KNOWN)


@pytest.mark.parametrize("name", EXAMPLES)
def test_plan_matches_the_schema_except_known_gaps(name: str) -> None:
    assert _errors(ResponsePlan, _load(name)["plan"]) == sorted(KNOWN[name]["plan"])


@pytest.mark.parametrize("name", EXAMPLES)
def test_response_matches_the_schema_except_known_gaps(name: str) -> None:
    assert _errors(AgentResponse, _load(name)["response"]) == sorted(KNOWN[name]["response"])


@pytest.mark.parametrize("name", EXAMPLES)
def test_plan_text_has_no_numerals_except_known_gaps(name: str) -> None:
    plan, _ = parse_plan(_load(name)["plan"])
    found = [i.message for i in check_plan_text(plan) if i.code == "narrative_numeral"]
    assert found == KNOWN[name]["plan_text"]


@pytest.mark.parametrize("name", EXAMPLES)
def test_examples_follow_the_answer_skeleton_and_one_currency(name: str) -> None:
    response = _load(name)["response"]
    assert check_skeleton(response["blocks"]) == []
    assert check_currency(response) == []


@pytest.mark.parametrize("name", EXAMPLES)
def test_lenient_parse_degrades_only_the_broken_blocks(name: str) -> None:
    raw = _load(name)["response"]
    response, issues = parse_response(raw)
    broken = {int(e.split(".")[1]) for e in KNOWN[name]["response"] if e.startswith("blocks.")}
    assert [b.block_id for b in response.blocks] == [b["block_id"] for b in raw["blocks"]]
    assert [b.placement.model_dump() for b in response.blocks] == [
        b["placement"] for b in raw["blocks"]
    ]
    assert response.status == ("degraded" if broken else raw["status"])
    assert {int(i.message.split(":")[0].split(".")[1]) for i in issues if i.block_id} == broken
    assert visible_tabs(response.blocks) == visible_tabs(raw["blocks"])
