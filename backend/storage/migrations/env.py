from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from backend.settings import get_settings
from backend.storage.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
