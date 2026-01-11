"""One-off backfill for partners.category_id.

This script performs a chunked backfill using keyset pagination to avoid long
locks during deploys.  It can be executed as a standalone script or invoked via
the Flask CLI (``flask backfill-partners-category``).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Iterable

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.pool import NullPool

try:  # pragma: no cover - optional dependency for precise error classes
    import psycopg.errors as pg_errors
except ModuleNotFoundError:  # pragma: no cover - fallback for psycopg2 or absence
    try:  # pragma: no cover - legacy psycopg2 compatibility
        import psycopg2.errors as pg_errors
    except ModuleNotFoundError:  # pragma: no cover - no driver-specific errors
        pg_errors = None

_PG_LOCK_ERRORS = (
    getattr(pg_errors, "LockNotAvailable", None),
    getattr(pg_errors, "QueryCanceled", None),
) if pg_errors else tuple()


logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 2000
RETRYABLE_PG_CODES = {"55P03", "57014"}
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 2.0


def _chunk_size_from_env(default: int = DEFAULT_CHUNK_SIZE) -> int:
    raw = os.getenv("BACKFILL_CHUNK")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid BACKFILL_CHUNK=%s provided; falling back to default %s", raw, default
        )
        return default
    return max(1, value)


def _should_retry(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)

    if orig is not None:
        pgcode = getattr(orig, "pgcode", None)
        if pgcode and pgcode in RETRYABLE_PG_CODES:
            return True
        if _PG_LOCK_ERRORS and isinstance(orig, _PG_LOCK_ERRORS):
            return True

    message = str(exc).lower()
    return "lock timeout" in message or "statement timeout" in message


def _ensure_timeouts(connection: sa.engine.Connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(text("SET lock_timeout = '5s'"))
    connection.execute(text("SET statement_timeout = '5min'"))


def _resolve_slug_column(engine: Engine) -> str:
    inspector = sa.inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("partners")}

    if "category" in columns:
        return "category"
    if "category_slug" in columns:
        return "category_slug"

    raise RuntimeError(
        "Unable to determine legacy category slug column on partners table"
    )


def _build_values_clause(rows: Iterable[dict[str, int]]) -> tuple[str, dict[str, int]]:
    value_tokens = []
    params: dict[str, int] = {}

    for index, row in enumerate(rows):
        partner_key = f"partner_id_{index}"
        category_key = f"category_id_{index}"
        value_tokens.append(f"(:{partner_key}, :{category_key})")
        params[partner_key] = row["partner_id"]
        params[category_key] = row["category_id"]

    values_sql = ", ".join(value_tokens)
    return values_sql, params


def run_backfill(
    engine: Engine,
    *,
    chunk_size: int | None = None,
    logger: logging.Logger | None = None,
) -> int:
    """Execute the backfill and return the number of updated rows."""

    log = logger or logging.getLogger(__name__)
    effective_chunk = chunk_size or _chunk_size_from_env()

    slug_column = _resolve_slug_column(engine)

    select_sql = text(
        f"""
        SELECT p.id AS partner_id, pc.id AS category_id
        FROM partners AS p
        JOIN partner_categories AS pc ON pc.slug = p.{slug_column}
        WHERE p.id > :last_id AND p.category_id IS NULL
        ORDER BY p.id
        LIMIT :limit
        """
    )

    updated = 0
    last_id = 0
    chunk_index = 0

    with engine.connect() as connection:
        _ensure_timeouts(connection)

        while True:
            attempt = 0
            while True:
                try:
                    rows = (
                        connection.execute(
                            select_sql, {"last_id": last_id, "limit": effective_chunk}
                        )
                        .mappings()
                        .all()
                    )
                except OperationalError as exc:
                    if _should_retry(exc) and attempt < MAX_RETRIES:
                        attempt += 1
                        sleep_for = RETRY_DELAY_SECONDS * attempt
                        log.warning(
                            "Chunk SELECT failed due to transient error (attempt %s/%s): %s",
                            attempt,
                            MAX_RETRIES,
                            exc,
                        )
                        time.sleep(sleep_for)
                        continue
                    raise
                break

            if not rows:
                break

            filtered_rows = [row for row in rows if row["category_id"] is not None]
            if not filtered_rows:
                last_id = rows[-1]["partner_id"]
                continue

            dialect_name = connection.dialect.name
            update_payload = [
                {"partner_id": row["partner_id"], "category_id": row["category_id"]}
                for row in filtered_rows
            ]

            if dialect_name == "sqlite":
                update_sql = text(
                    "UPDATE partners SET category_id = :category_id WHERE id = :partner_id"
                )
                params: dict[str, int] | list[dict[str, int]] = update_payload
            else:
                values_clause, params = _build_values_clause(filtered_rows)
                update_sql = text(
                    f"""
                    UPDATE partners AS p
                    SET category_id = v.category_id
                    FROM (VALUES {values_clause}) AS v(id, category_id)
                    WHERE p.id = v.id
                    """
                )

            if connection.in_transaction():
                connection.commit()

            attempt = 0
            while True:
                try:
                    with connection.begin():
                        connection.execute(update_sql, params)
                except OperationalError as exc:
                    if _should_retry(exc) and attempt < MAX_RETRIES:
                        attempt += 1
                        sleep_for = RETRY_DELAY_SECONDS * attempt
                        log.warning(
                            "Chunk UPDATE failed due to transient error (attempt %s/%s): %s",
                            attempt,
                            MAX_RETRIES,
                            exc,
                        )
                        time.sleep(sleep_for)
                        continue
                    raise
                break

            last_id = rows[-1]["partner_id"]
            chunk_index += 1
            updated += len(filtered_rows)

            log.info(
                "Backfilled chunk %s: %s rows updated (last partner id %s)",
                chunk_index,
                len(filtered_rows),
                last_id,
            )

        remaining = connection.execute(
            text("SELECT COUNT(*) FROM partners WHERE category_id IS NULL")
        ).scalar_one()

    if remaining:
        log.warning(
            "Backfill completed with %s partners still missing category_id", remaining
        )
    else:
        log.info("Backfill completed with no remaining NULL category_id values")

    return updated


def _build_engine_from_env() -> Engine:
    database_url = (
        os.getenv("DATABASE_URL")
        or os.getenv("SQLALCHEMY_DATABASE_URI")
        or os.getenv("DB_URI")
    )

    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")

    return sa.create_engine(
        database_url,
        poolclass=NullPool,
        future=True,
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    try:
        engine = _build_engine_from_env()
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.error("Unable to initialise database engine: %s", exc)
        return 1

    try:
        updated = run_backfill(engine)
    except SQLAlchemyError as exc:  # pragma: no cover - SQLAlchemy specific failure
        logger.exception("Backfill failed due to SQLAlchemy error: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover - defensive catch-all
        logger.exception("Backfill failed: %s", exc)
        return 1
    finally:
        engine.dispose()

    logger.info("Backfill completed successfully: %s rows updated", updated)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
