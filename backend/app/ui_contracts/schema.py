"""One JSON Schema for every contract the client reads (docs/08 §2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from backend.app.ui_contracts.plan import ResponsePlan
from backend.app.ui_contracts.response import (
    AccountList,
    AccountView,
    ActivityFeed,
    AgentResponse,
    CalculationView,
    CategoryCorrected,
    CategoryList,
    DetectedFlows,
    FeaturesPayload,
    ForecastView,
    Healthz,
    HomeInsights,
    ImportHistory,
    ImportSummary,
    IncomeStreamView,
    ProfileView,
    SimulationView,
    TransactionPage,
)

# Top-level documents, in a stable order. Each gets a generated TS type and guard.
ROOTS: tuple[type[BaseModel], ...] = (
    AgentResponse,
    ResponsePlan,
    Healthz,
    FeaturesPayload,
    ImportSummary,
    ForecastView,
    SimulationView,
    ProfileView,
    TransactionPage,
    CalculationView,
    AccountList,
    AccountView,
    DetectedFlows,
    CategoryList,
    CategoryCorrected,
    ImportHistory,
    HomeInsights,
    IncomeStreamView,
    ActivityFeed,
)


def contracts_schema() -> dict[str, Any]:
    _, schema = models_json_schema(
        [(model, "validation") for model in ROOTS], ref_template="#/$defs/{model}"
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "UiContracts",
        "description": "Generated from backend/app/ui_contracts by tools/export_schemas.py. "
        "Do not edit.",
        "x-roots": [model.__name__ for model in ROOTS],
        "$defs": schema["$defs"],
    }
