from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.settings import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("FORESIGHT_BUILD_SHA", "abc1234")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_healthz_reports_deploy_sha(client: TestClient) -> None:
    body = client.get("/healthz").json()
    assert body["sha"] == "abc1234"
    assert body["status"] == "ok"
    assert body["database"] is None
    assert body["ai"] in {"ok", "low", "unavailable"}  # a word only, never a balance figure


def test_features_endpoint_lists_flags(client: TestClient) -> None:
    features = client.get("/api/features").json()["features"]
    keys = {f["key"] for f in features}
    assert {"forecast", "checked_advice", "ask"} <= keys
    assert all(isinstance(f["enabled"], bool) for f in features)


def test_healthz_fails_when_database_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding: readiness must fail (503) so health checks never pass a broken deploy."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none")
    get_settings.cache_clear()
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 503
    assert response.json()["database"] is False


def test_runtime_env_files_cannot_override_the_build_sha() -> None:
    """Review finding: a DEPLOY_SHA/FORESIGHT_BUILD_SHA in .env would mask the image's commit
    and make post-deploy smoke time out. Neither the template nor production compose sets it."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    env_template = (root / ".env.example").read_text(encoding="utf-8")
    prod_compose = (root / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    for text in (env_template, prod_compose):
        assert "FORESIGHT_BUILD_SHA=" not in text
        assert "DEPLOY_SHA=" not in text
    assert "ENV FORESIGHT_BUILD_SHA=" in (root / "backend" / "Dockerfile").read_text()
