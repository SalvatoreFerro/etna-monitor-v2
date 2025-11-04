"""Alembic environment configuration without Flask app bootstrap."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import db  # noqa: F401 - ensures models are imported

# Ensure application bootstrap knows we are running inside Alembic.
os.environ.setdefault("ALEMBIC_RUNNING", "1")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _get_database_url() -> str:
    try:
        return os.environ["DATABASE_URL"]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError("DATABASE_URL environment variable is required for migrations") from exc


database_url = _get_database_url()
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = db.Model.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
