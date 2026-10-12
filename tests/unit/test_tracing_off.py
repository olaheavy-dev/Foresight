from __future__ import annotations

import os

import pytest

from backend.settings import disable_external_tracing, get_settings


def test_external_tracing_forced_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    disable_external_tracing()
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"


def test_loading_settings_disables_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    get_settings.cache_clear()
    get_settings()
    assert os.environ["LANGSMITH_TRACING"] == "false"
