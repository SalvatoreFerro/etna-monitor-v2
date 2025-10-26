import logging
from logging.config import fileConfig

from flask import current_app
from alembic import context

from app import create_app


_app_context = None


def _ensure_app_context() -> None:
    """Ensure that a Flask app context is available for Alembic."""

    global _app_context
    try:
        # Accessing an attribute forces the proxy to resolve the app.
        current_app.name  # type: ignore[attr-defined]
    except RuntimeError:
        app = create_app()
        _app_context = app.app_context()
        _app_context.push()


_ensure_app_context()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')


def _get_metadata():
    try:
        return current_app.extensions['migrate'].db.metadata
    except RuntimeError:
        return None


target_metadata = _get_metadata()

def run_migrations_offline() -> None:
    url = current_app.config.get('SQLALCHEMY_DATABASE_URI')
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = current_app.extensions['migrate'].db.engine

    with connectable.connect() as connection:
        render_as_batch = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=render_as_batch,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
