"""The generated frontend contracts are in sync with the Pydantic models (docs/08 §2)."""

from __future__ import annotations

import json
import shutil

import pytest

from tools import export_schemas


def test_schema_json_is_up_to_date() -> None:
    on_disk = export_schemas.SCHEMA_FILE.read_text(encoding="utf-8")
    assert on_disk == export_schemas.render_schema(), "run python tools/export_schemas.py"


def test_schema_has_every_root_and_block() -> None:
    schema = json.loads(export_schemas.render_schema())
    assert set(schema["x-roots"]) <= set(schema["$defs"])
    blocks = schema["$defs"]["AgentResponse"]["properties"]["blocks"]["items"]
    assert set(blocks["discriminator"]["mapping"]) == {
        "Narrative", "ClarifyingQuestion", "FinancialMetricGroup", "SpendingBreakdownChart",
        "CashFlowForecastChart", "ScenarioComparison", "TransactionTable", "RiskAssessment",
        "InterventionCard", "GoalProjection", "EvidencePanel", "AgentExecutionTimeline",
    }  # fmt: skip


@pytest.mark.skipif(
    shutil.which("node") is None
    or not (export_schemas.FRONTEND / "node_modules" / "json-schema-to-typescript").exists(),
    reason="needs Node and `npm ci` in frontend/",
)
def test_generated_typescript_is_up_to_date() -> None:
    assert export_schemas.main(["--check"]) == 0
