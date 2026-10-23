"""A blank value in the environment must fall back to the default, never become an empty setting."""

from __future__ import annotations

import pytest

from backend.settings import Settings


def test_blank_model_ids_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MODEL_FAST", "MODEL_REASONING", "MODEL_VERIFIER"):
        monkeypatch.setenv(name, "")
    settings = Settings()
    assert settings.model_fast
    assert settings.model_reasoning
    assert settings.model_verifier
