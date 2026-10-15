"""The API against a disposable, migrated PostgreSQL database seeded with the P1/P2 demo."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from backend.app.main import create_app
from backend.app.session import CSRF_HEADER
from backend.pipeline.seed_demo import seed_all
from backend.settings import get_settings
from tests.integration.storage.disposable import configured_database_is_untouched, migrated_engine

CLIENT = {CSRF_HEADER: "web"}

__all__ = ["configured_database_is_untouched", "migrated_engine"]


@pytest.fixture(scope="module")
def seeded(migrated_engine: Engine) -> Engine:
    with sessionmaker(bind=migrated_engine, expire_on_commit=False)() as session:
        seed_all(session)
    return migrated_engine


@pytest.fixture
def api(seeded: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client bound to the disposable database. https, because the cookie is Secure."""
    monkeypatch.setenv("DATABASE_URL", seeded.url.render_as_string(hide_password=False))
    monkeypatch.setenv("SESSION_SECRET", "test-only-secret")
    get_settings.cache_clear()
    with TestClient(create_app(), base_url="https://testserver", headers=CLIENT) as client:
        yield client
    get_settings.cache_clear()


class BrowserClient(TestClient):
    """A browser on this app's own pages: it sends the client header every write needs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["headers"] = {**CLIENT, **(kwargs.get("headers") or {})}
        super().__init__(*args, **kwargs)


@pytest.fixture
def make_client(seeded: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[type[TestClient]]:
    """For tests that need two browsers (two separate cookie jars)."""
    monkeypatch.setenv("DATABASE_URL", seeded.url.render_as_string(hide_password=False))
    monkeypatch.setenv("SESSION_SECRET", "test-only-secret")
    get_settings.cache_clear()
    yield BrowserClient
    get_settings.cache_clear()
