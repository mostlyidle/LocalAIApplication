"""Alembic environment configuration.

Runs migrations against the application database using synchronous SQLAlchemy.
The target metadata is imported from the ORM models so Alembic can auto-detect
schema changes for ``--autogenerate``.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the backend package is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.models.db_models import Base  # noqa: E402

# Alembic Config object — provides access to alembic.ini values.
config = context.config

# Interpret the config file for Python logging (if present).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy MetaData for autogenerate support.
target_metadata = Base.metadata

# Build a synchronous URL from the async settings URL.
# aiosqlite → pysqlite (standard sqlite3 driver).
_sync_url = settings.app_database_url.replace("+aiosqlite", "")
config.set_main_option("sqlalchemy.url", _sync_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine. Calls to
    ``context.execute()`` emit the given SQL to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an Engine and associates a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
