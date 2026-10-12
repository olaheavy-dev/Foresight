from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.settings import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DEPLOY_SHA", "abc1234")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_healthz_reports_deploy_sha(client: TestClient) -> None:
    body = client.get("/healthz").json()
    assert body["sha"] == "abc1234"
    assert body["status"] == "ok"
    assert body["database"] is None


def test_features_endpoint_lists_flags(client: TestClient) -> None:
    features = client.get("/api/features").json()["features"]
    keys = {f["key"] for f in features}
    assert {"forecast", "checked_advice", "ask"} <= keys
    assert all(isinstance(f["enabled"], bool) for f in features)
