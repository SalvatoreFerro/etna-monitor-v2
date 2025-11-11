"""Custom Flask CLI commands."""

from __future__ import annotations

import logging
from typing import Optional

import click
from flask import current_app
from flask import Flask

from .models import db
from .scripts.run_backfill_partners_category import DEFAULT_CHUNK_SIZE, run_backfill


def register_cli_commands(app: Flask) -> None:
    """Register application specific CLI commands."""

    @app.cli.command("backfill-partners-category")
    @click.option(
        "--chunk-size",
        type=int,
        default=None,
        help=(
            "Number of partners processed per batch (defaults to BACKFILL_CHUNK "
            f"or {DEFAULT_CHUNK_SIZE})."
        ),
    )
    def backfill_partners_category(chunk_size: Optional[int]) -> None:
        """Backfill partners.category_id in an online-safe manner."""

        logger = current_app.logger or logging.getLogger(__name__)
        engine = db.engine

        try:
            updated = run_backfill(
                engine,
                chunk_size=chunk_size if chunk_size and chunk_size > 0 else None,
                logger=logger,
            )
        except Exception as exc:
            logger.exception("Backfill failed")
            raise click.ClickException(str(exc)) from exc

        click.echo(f"Backfill completed successfully: {updated} partners updated")

