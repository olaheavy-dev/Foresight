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
    # A blank value in .env (e.g. `MODEL_FAST=`) means "use the default", never "".
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # Where model calls go: OpenAI directly (owner decision 20 Oct 2026, docs/00 §12 item 14; the
    # Mesh gateway was removed on 23 Oct). Any other value, such as a stale "mesh", fails at
    # start-up. Model IDs keep their `openai/` prefix, so recordings replay unchanged; every tier's
    # primary must be an `openai/` model (start-up refuses a stale override) and other providers'
    # fallbacks are skipped. The old MESH_* names are no longer read (renamed 23 Oct 2026): an env
    # still setting them gets these defaults.
    model_provider: str = "openai"
    openai_api_key: str = ""
    # Model IDs per tier (docs/06 §13). Owner decision 20 Oct 2026 (docs/00 §12 item 14): every tier
    # on OpenAI, the Verifier judge a different model from the Advisor. GPT-6 Sol as Advisor won the
    # dev-case trial (evals/results/20261020T2030Z_openai_advisor_trial); GPT-6.1 Sol stays
    # the judge. Neither has a fallback: each's only alternative is the other's model, and the
    # same model must never write and check a recommendation (Codex on #67). An Advisor failure
    # degrades to the deterministic answer.
    # GPT-5.6 Luna Pro failed whole-answer accuracy and latency on 13 Oct (evals/CHANGELOG.md).
    model_fast: str = "openai/gpt-6-luna"
    model_fast_fallback: str = "openai/gpt-6-sol"
    model_reasoning: str = "openai/gpt-6-sol"
    model_reasoning_fallback: str = ""
    model_verifier: str = "openai/gpt-6.1-sol"
    model_verifier_fallback: str = ""
    # Per-call timeouts by tier (docs/05 §6.4); transport retries are ours, not the SDK's.
    model_timeout_fast_seconds: float = 8.0
    model_timeout_reasoning_seconds: float = 25.0
    model_max_retries: int = 2
    # live: call the model · record: call it and save each exchange · replay: answer only from saved
    # exchanges (no key, no network); a request that was never recorded raises CassetteMiss.
    model_cassette_mode: str = "live"
    model_cassette_dir: str = "evals/cassettes"
    # Project-wide cap on model spend per UTC day (backend/llm/spend_guard.py); 0 disables it.
    model_daily_budget_usd: float = 0.50
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
