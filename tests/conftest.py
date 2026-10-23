from __future__ import annotations

import os

import pytest

from backend.settings import Settings

# Tests never read the developer's .env: it can hold a live model key, and a test that reached
# a live model would spend real credit (it happened once on 15 Oct 2026). CI has no .env anyway;
# anything a test needs, it sets explicitly.
Settings.model_config["env_file"] = None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="DATABASE_URL not set; run `make test-db` with PostgreSQL")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)
