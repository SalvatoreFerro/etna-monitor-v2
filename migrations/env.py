"""Alembic environment configuration without Flask app bootstrap."""

from __future__ import annotations

import importlib
import os
import sys
from logging.config import fileConfig
from pathlib import Path
from types import ModuleType

# Ensure application bootstrap knows we are running inside Alembic before any
# application modules are imported. This prevents ``app.__init__`` from running
# side-effects (scheduler, schema guards, etc.) during Alembic execution.
os.environ.setdefault("ALEMBIC_RUNNING", "1")

from alembic import context
from sqlalchemy import engine_from_config, pool

def _load_models_module():
    """Load app.models without executing app/__init__.py side effects."""

    app_root = Path(__file__).resolve().parents[1] / "app"
    if "app" not in sys.modules:
        app_pkg = ModuleType("app")
        app_pkg.__path__ = [str(app_root)]
        sys.modules["app"] = app_pkg

    return importlib.import_module("app.models")


models = _load_models_module()
db = models.db

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]

    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + url[len("postgresql+psycopg2://"):]

    if url.startswith("postgresql://") and not url.startswith("postgresql+psycopg://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]

    return url


def _get_database_url() -> str:
    if "DATABASE_URL" in os.environ:
        return os.environ["DATABASE_URL"]

    config_url = config.get_main_option("sqlalchemy.url")
    if config_url:
        return config_url

    raise RuntimeError("DATABASE_URL environment variable is required for migrations")


database_url = _normalize_database_url(_get_database_url())
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
