import os
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("TELEGRAM_BOT_MODE", "off")

from app import create_app
from app.models import db


def _configure_environment(tmp_path):
    db_path = tmp_path / "test.db"
    if db_path.exists():
        db_path.unlink()
    database_uri = f"sqlite:///{db_path}"
    os.environ["DATABASE_URL"] = database_uri
    return database_uri


def _run_alembic_upgrade(database_uri: str) -> None:
    alembic_cfg = AlembicConfig()
    alembic_cfg.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "migrations"),
    )
    alembic_cfg.set_main_option("sqlalchemy.url", database_uri)
    command.upgrade(alembic_cfg, "head")


def test_alembic_upgrade_creates_required_schema(tmp_path):
    database_uri = _configure_environment(tmp_path)
    app = create_app({"TESTING": True})

    with app.app_context():
        with db.engine.begin() as conn:
            conn.execute(
                sa.text(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY,
                        email TEXT NOT NULL,
                        password_hash TEXT,
                        is_admin INTEGER DEFAULT 0,
                        is_premium INTEGER DEFAULT 0,
                        premium INTEGER DEFAULT 0,
                        premium_lifetime INTEGER DEFAULT 0,
                        subscription_status TEXT,
                        chat_id TEXT
                    )
                    """
                )
            )
        db.reflect()
        _run_alembic_upgrade(database_uri)

        inspector = sa.inspect(db.engine)
        user_columns = {col["name"]: col for col in inspector.get_columns("users")}
        assert "plan_type" in user_columns
        assert user_columns["plan_type"]["nullable"] is False
        default = user_columns["plan_type"].get("default")
        if default is not None:
            assert "free" in str(default)

        # Ensure Google OAuth support columns are created
        assert "google_id" in user_columns
        assert "name" in user_columns
        assert "picture_url" in user_columns

        assert "partners" in inspector.get_table_names()
        partner_indexes = {
            index["name"] for index in inspector.get_indexes("partners")
        }
        assert "idx_partners_visible" in partner_indexes
        assert "idx_partners_verified_created" in partner_indexes

        user_indexes = {index["name"] for index in inspector.get_indexes("users")}
        assert "ix_users_google_id_unique" in user_indexes

        verified_col = {
            col["name"]: col for col in inspector.get_columns("partners")
        }["verified"]
        default_verified = verified_col.get("default")
        if default_verified is not None:
            assert "0" in str(default_verified) or "false" in str(default_verified).lower()

