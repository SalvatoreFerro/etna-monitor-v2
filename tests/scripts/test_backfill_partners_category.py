import logging
import math
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.scripts.run_backfill_partners_category import run_backfill


def test_backfill_partners_category_dry_run(tmp_path, caplog):
    db_path = tmp_path / "partners.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    total_rows = 10_000
    category_slugs = ["guide", "hotel", "ristoranti", "esperienze", "cucina"]

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE partner_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE partners (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    category TEXT,
                    category_id INTEGER
                )
                """
            )
        )

        connection.execute(
            text("INSERT INTO partner_categories (slug) VALUES (:slug)"),
            [{"slug": slug} for slug in category_slugs],
        )

        partner_rows = [
            {
                "name": f"Partner {idx}",
                "category": category_slugs[idx % len(category_slugs)],
            }
            for idx in range(total_rows)
        ]

        connection.execute(
            text("INSERT INTO partners (name, category) VALUES (:name, :category)"),
            partner_rows,
        )

    caplog.set_level(logging.INFO, logger="app.scripts.run_backfill_partners_category")

    updated = run_backfill(engine, chunk_size=1_200)
    assert updated == total_rows

    with engine.connect() as connection:
        remaining = connection.execute(
            text("SELECT COUNT(*) FROM partners WHERE category_id IS NULL")
        ).scalar_one()
        assert remaining == 0

        categories_joined = connection.execute(
            text(
                "SELECT COUNT(*) FROM partners p JOIN partner_categories pc "
                "ON pc.id = p.category_id"
            )
        ).scalar_one()
        assert categories_joined == total_rows

    chunk_logs = [
        record for record in caplog.records if "Backfilled chunk" in record.getMessage()
    ]
    assert len(chunk_logs) >= math.ceil(total_rows / 1_200)

    caplog.clear()
    updated_again = run_backfill(engine, chunk_size=1_200)
    assert updated_again == 0

    with engine.connect() as connection:
        remaining_again = connection.execute(
            text("SELECT COUNT(*) FROM partners WHERE category_id IS NULL")
        ).scalar_one()
        assert remaining_again == 0
