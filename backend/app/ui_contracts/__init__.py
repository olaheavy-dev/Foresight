"""Generative-UI contracts (docs/08): the LLM-facing plan, the hydrated response and the checks
between them. Pydantic models here are the source of truth; `tools/export_schemas.py` exports
their JSON Schema and the generated TypeScript types and guards in `frontend/src/ui-contracts/`."""

from backend.app.ui_contracts.blocks import BLOCK_TYPES, Block
from backend.app.ui_contracts.plan import BlockPlan, ResponsePlan
from backend.app.ui_contracts.response import (
    AgentResponse,
    FeaturesPayload,
    ForecastView,
    Healthz,
    ImportSummary,
    SimulationView,
)

__all__ = [
    "BLOCK_TYPES",
    "AgentResponse",
    "Block",
    "BlockPlan",
    "FeaturesPayload",
    "ForecastView",
    "Healthz",
    "ImportSummary",
    "ResponsePlan",
    "SimulationView",
]
