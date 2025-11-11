"""Render pre-deploy helper to run Alembic migrations safely."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )


def _alembic_config(project_root: Path) -> Config:
    """Return an Alembic ``Config`` bound to the project migrations directory."""

    config_path = project_root / "alembic.ini"
    if not config_path.exists():
        raise FileNotFoundError(f"Unable to locate alembic.ini at {config_path}")

    cfg = Config(str(config_path))

    script_location = cfg.get_main_option("script_location")
    migrations_path = project_root / "migrations"
    if not script_location or script_location == "migrations":
        cfg.set_main_option("script_location", str(migrations_path))

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required to run migrations")

    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def run() -> None:
    _configure_logging()

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    os.environ.setdefault("ALEMBIC_RUNNING", "1")

    config = _alembic_config(project_root)
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    if len(heads) > 1:
        target = "heads"
        logging.warning(
            "Multiple Alembic heads detected (%s); upgrading all heads",
            ", ".join(heads),
        )
    else:
        target = "head"
        logging.info("Upgrading database to Alembic head %s", heads[0] if heads else "<unknown>")

    command.upgrade(config, target)
    logging.info("Alembic upgrade %s completed successfully", target)


def main() -> None:
    try:
        run()
    except Exception:  # pragma: no cover - safety for deployment script
        logging.exception("Alembic migration execution failed")
        raise


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
