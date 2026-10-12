"""Runtime settings, read from the environment (and a local, gitignored .env)."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# No run traces may leave the app: LangGraph/LangChain would send them to LangSmith if these
# were enabled, and traces contain financial data (docs/05 §3.1, rule 3).
_TRACING_ENV_VARS = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")


def disable_external_tracing() -> None:
    for name in _TRACING_ENV_VARS:
        os.environ[name] = "false"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mesh_api_key: str = ""
    mesh_base_url: str = "https://api.meshapi.ai/v1"
    mesh_model_fast: str = ""
    mesh_model_fast_fallback: str = ""
    mesh_model_reasoning: str = ""
    mesh_model_reasoning_fallback: str = ""
    mesh_timeout_seconds: float = 30.0
    mesh_max_retries: int = 2

    database_url: str = ""
    deploy_sha: str = "local"
    features_file: str = "features.yaml"


@lru_cache
def get_settings() -> Settings:
    disable_external_tracing()
    return Settings()
