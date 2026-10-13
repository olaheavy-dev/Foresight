"""Disposable PostgreSQL databases for integration tests (pattern from test_migrations.py).

DATABASE_URL only supplies the server and credentials. Each fixture creates a fresh
`foresight_test_<random>` database, migrates it and drops it WITH (FORCE) afterwards, and a guard
checks that the configured database's tables are unchanged.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


@contextmanager
def disposable_database() -> Iterator[str]:
    server = make_url(os.environ["DATABASE_URL"])
    name = f"foresight_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield server.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def alembic_config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.fixture(scope="module", autouse=True)
def configured_database_is_untouched() -> Iterator[None]:
    engine = create_engine(os.environ["DATABASE_URL"])
    before = set(inspect(engine).get_table_names())
    yield
    after = set(inspect(engine).get_table_names())
    engine.dispose()
    assert after == before


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[Engine]:
    with disposable_database() as url:
        assert make_url(url).database != make_url(os.environ["DATABASE_URL"]).database
        command.upgrade(alembic_config(url), "head")
        engine = create_engine(url)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=migrated_engine, expire_on_commit=False)() as s:
        yield s
