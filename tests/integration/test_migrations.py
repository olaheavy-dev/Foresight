"""Migrations run against a real PostgreSQL (CI service container or `docker compose`)."""

from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.postgres


@pytest.fixture
def alembic_config() -> Config:
    return Config("alembic.ini")


def test_upgrade_and_downgrade(alembic_config: Config) -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    command.upgrade(alembic_config, "head")
    assert "workspace" in inspect(engine).get_table_names()
    command.downgrade(alembic_config, "base")
    assert "workspace" not in inspect(engine).get_table_names()
    command.upgrade(alembic_config, "head")


def test_workspace_ids_must_use_the_wsp_prefix(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(os.environ["DATABASE_URL"])
    insert = text(
        "INSERT INTO workspace (id, name, country, home_currency, locale, timezone) "
        "VALUES (:id, 'Test', 'GB', 'GBP', 'en-GB', 'Europe/London')"
    )
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(insert, {"id": "prof_01TEST"})
    with engine.begin() as conn:
        conn.execute(insert, {"id": "wsp_01TEST"})
        conn.execute(text("DELETE FROM workspace WHERE id = 'wsp_01TEST'"))
