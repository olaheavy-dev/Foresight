from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="DATABASE_URL not set; run `make test-db` with PostgreSQL")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)
