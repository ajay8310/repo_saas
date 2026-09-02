"""Alembic environment script.

This file is executed by Alembic for every migration command.  It reads
``DATABASE_URL`` from the environment (via ``app.config.Settings``) so that
the same connection string used at runtime drives migrations too.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection

from alembic import context

# Import metadata from the ORM models so Alembic can auto-generate migrations.
# The import will be populated as models are added in task 1.3.
# from app.models import Base  # noqa: F401 (uncomment in task 1.3)

# ---------------------------------------------------------------------------
# Alembic config object
# ---------------------------------------------------------------------------
config = context.config

# Set up Python logging from the alembic.ini [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Provide metadata for auto-generation.  Will be set to Base.metadata in task 1.3.
target_metadata = None

# Override the sqlalchemy.url with the value from the runtime config / env.
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url:
    # Alembic needs a synchronous DSN even when the app uses asyncpg.
    # Replace the async driver prefix so Alembic can use psycopg2.
    _sync_url = _db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    config.set_main_option("sqlalchemy.url", _sync_url)


# ---------------------------------------------------------------------------
# Offline migrations (no live DB connection)
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations (connects to a live DB)
# ---------------------------------------------------------------------------

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_sync_migrations() -> None:
    """Run migrations using a sync engine (psycopg2) from the converted URL."""
    from sqlalchemy import engine_from_config

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


def run_migrations_online() -> None:
    run_sync_migrations()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
