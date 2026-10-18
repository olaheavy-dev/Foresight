"""Runtime settings, read from the environment (and a local, gitignored .env)."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# No run traces may leave the app: LangGraph/LangChain would send them to LangSmith if these
# were enabled, and traces contain financial data (docs/05 §3.1, rule 3).
_TRACING_ENV_VARS = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")


def disable_external_tracing() -> None:
    for name in _TRACING_ENV_VARS:
        os.environ[name] = "false"


class Settings(BaseSettings):
    # A blank value in .env (e.g. `MESH_MODEL_FAST=`) means "use the default", never "".
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    mesh_api_key: str = ""
    # Model IDs per tier (docs/06 §13), chosen from Mesh's catalogue (docs/00 §12.1). The Verifier
    # judge uses a different provider from the Advisor so the check is independent.
    mesh_model_fast: str = "openai/gpt-6-luna"
    mesh_model_fast_fallback: str = "anthropic/claude-haiku-5.5"
    # Owner decision 13 Oct 2026 under the core-metrics rule (docs/00 §8): GPT-5.6 Luna Pro was
    # tried on the reasoning tier and failed accuracy and latency (evals/CHANGELOG.md), so the
    # Advisor/Analyst stay on Claude Sonnet 5.5 and the judge on GPT-6.1 Sol (another provider).
    mesh_model_reasoning: str = "anthropic/claude-sonnet-5.5"
    mesh_model_reasoning_fallback: str = "google/gemini-3.1-pro"
    mesh_model_verifier: str = "openai/gpt-6.1-sol"
    mesh_model_verifier_fallback: str = "google/gemini-3.1-pro"
    # Per-call timeouts by tier (docs/05 §6.4); transport retries are ours, not the SDK's.
    mesh_timeout_fast_seconds: float = 8.0
    mesh_timeout_reasoning_seconds: float = 25.0
    mesh_max_retries: int = 2
    # live: call Mesh · record: call Mesh and save each exchange · replay: answer only from saved
    # exchanges (no key, no network); a request that was never recorded raises CassetteMiss.
    mesh_cassette_mode: str = "live"
    mesh_cassette_dir: str = "evals/cassettes"
    # AI availability (backend/mesh/availability.py): below the first, status is `low`; at or
    # below the per-question worst case, AI answers pause. Figures never reach users or logs.
    mesh_low_balance_usd: float = 2.00
    mesh_question_worst_case_usd: float = 0.30
    # Project-wide cap on model spend per UTC day (backend/mesh/spend_guard.py); 0 disables it.
    mesh_daily_budget_usd: float = 0.50
    # Guests' AI work per network per UTC day (backend/app/network_cap.py); 0 disables a cap.
    guest_network_daily_questions: int = 20
    guest_network_daily_checks: int = 3
    # Where the visitor's address comes from behind a public edge (a CDN in front of the proxy):
    # a header the edge sets and the origin only accepts from it (e.g. CF-Connecting-IP), and/or
    # trusted proxy ranges skipped when reading X-Forwarded-For from the right (comma-separated
    # CIDRs). Unset: the first public X-Forwarded-For hop from the right, as the proxy wrote it.
    client_ip_header: str = ""
    trusted_proxy_cidrs: str = ""

    database_url: str = ""
    # Baked into the image at build time (backend/Dockerfile). Deliberately a name that no
    # .env file uses, so runtime configuration cannot mask the build being served.
    build_sha: str = Field(default="local", validation_alias="FORESIGHT_BUILD_SHA")
    features_file: str = "features.yaml"
    # Signs the short-lived Google sign-in cookie (docs/05 §5.9). Empty → derived from the Google
    # client secret.
    session_secret: str = ""
    session_cookie_secure: bool = True
    # Google sign-in (OIDC, owner decision 15 Oct 2026). Sign-in is offered only when both are set;
    # guests can always use the app. PUBLIC_BASE_URL builds the registered redirect URI.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    public_base_url: str = "http://localhost:3000"
    # Private demo copies kept seeded ahead of time per persona (backend/app/demo_pool.py); 0 seeds
    # each one inline, in the request.
    demo_pool_size: int = 3
    # Run queued proactive analyses in a background thread (backend/app/proactive.py). Tests turn
    # it off and run jobs explicitly.
    proactive_worker: bool = True


@lru_cache
def get_settings() -> Settings:
    disable_external_tracing()
    return Settings()
