"""Migration round trips run in a disposable database, never the one DATABASE_URL names.

DATABASE_URL only supplies the server and credentials: each test session creates a fresh
`foresight_test_<random>` database, migrates it, and drops it afterwards, so running the suite
against a development or demo database can never delete its data.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module", autouse=True)
def configured_database_is_untouched() -> Iterator[None]:
    """Review finding: no test may migrate or downgrade the database DATABASE_URL names.
    Its tables (including alembic_version) must be identical before and after this module."""
    engine = create_engine(os.environ["DATABASE_URL"])
    before = set(inspect(engine).get_table_names())
    yield
    after = set(inspect(create_engine(os.environ["DATABASE_URL"])).get_table_names())
    engine.dispose()
    assert after == before


@pytest.fixture(scope="module")
def disposable_url() -> Iterator[str]:
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


@pytest.fixture
def alembic_config(disposable_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", disposable_url.replace("%", "%%"))
    return config


def test_uses_a_disposable_database(disposable_url: str) -> None:
    assert make_url(disposable_url).database != make_url(os.environ["DATABASE_URL"]).database


def test_upgrade_and_downgrade(alembic_config: Config, disposable_url: str) -> None:
    engine = create_engine(disposable_url)
    command.upgrade(alembic_config, "head")
    assert "workspace" in inspect(engine).get_table_names()
    command.downgrade(alembic_config, "base")
    assert "workspace" not in inspect(engine).get_table_names()
    command.upgrade(alembic_config, "head")
    engine.dispose()


def test_workspace_ids_must_use_the_wsp_prefix(alembic_config: Config, disposable_url: str) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(disposable_url)
    insert = text(
        "INSERT INTO workspace (id, name, country, home_currency, locale, timezone) "
        "VALUES (:id, 'Test', 'GB', 'GBP', 'en-GB', 'Europe/London')"
    )
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(insert, {"id": "prof_01TEST"})
    with engine.begin() as conn:
        conn.execute(insert, {"id": "wsp_01TEST"})
    engine.dispose()
