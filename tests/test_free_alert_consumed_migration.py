"""Test free_alert_consumed column type migration."""
import os
import tempfile
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("TELEGRAM_BOT_MODE", "off")

from app import create_app
from app.models import db


def test_free_alert_consumed_integer_to_boolean_conversion():
    """Test that migration converts INTEGER free_alert_consumed to BOOLEAN."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        database_uri = f"sqlite:///{db_path}"
        os.environ["DATABASE_URL"] = database_uri
        
        app = create_app({"TESTING": True})
        
        with app.app_context():
            # Create initial users table with free_alert_consumed as INTEGER
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
                            chat_id TEXT,
                            free_alert_consumed INTEGER DEFAULT 0
                        )
                        """
                    )
                )
                
                # Insert test data with INTEGER values
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO users (email, free_alert_consumed) 
                        VALUES 
                            ('test1@example.com', 0),
                            ('test2@example.com', 1),
                            ('test3@example.com', NULL)
                        """
                    )
                )
            
            # Run the migration
            alembic_cfg = AlembicConfig()
            alembic_cfg.set_main_option(
                "script_location",
                str(Path(__file__).resolve().parents[1] / "migrations"),
            )
            alembic_cfg.set_main_option("sqlalchemy.url", database_uri)
            
            # Only run up to our migration
            command.upgrade(alembic_cfg, "20240702_add_plan_fields")
            
            # Verify the column exists and data is converted correctly
            inspector = sa.inspect(db.engine)
            user_columns = {col["name"]: col for col in inspector.get_columns("users")}
            
            assert "free_alert_consumed" in user_columns
            # In SQLite, BOOLEAN is stored as INTEGER, so we check nullable and default
            assert user_columns["free_alert_consumed"]["nullable"] is False
            
            # Check that data was preserved correctly
            with db.engine.begin() as conn:
                result = conn.execute(
                    sa.text(
                        """
                        SELECT email, free_alert_consumed 
                        FROM users 
                        ORDER BY email
                        """
                    )
                ).fetchall()
                
                assert len(result) == 3
                # In SQLite, FALSE=0, TRUE=1
                assert result[0][1] == 0  # test1: was 0, should be FALSE (0)
                assert result[1][1] == 1  # test2: was 1, should be TRUE (1)
                assert result[2][1] == 0  # test3: was NULL, should be FALSE (0)


def test_free_alert_consumed_missing_column():
    """Test that migration creates free_alert_consumed as BOOLEAN when missing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        database_uri = f"sqlite:///{db_path}"
        os.environ["DATABASE_URL"] = database_uri
        
        app = create_app({"TESTING": True})
        
        with app.app_context():
            # Create initial users table WITHOUT free_alert_consumed
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
                
                # Insert test data
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO users (email) 
                        VALUES ('test@example.com')
                        """
                    )
                )
            
            # Run the migration
            alembic_cfg = AlembicConfig()
            alembic_cfg.set_main_option(
                "script_location",
                str(Path(__file__).resolve().parents[1] / "migrations"),
            )
            alembic_cfg.set_main_option("sqlalchemy.url", database_uri)
            
            # Only run up to our migration
            command.upgrade(alembic_cfg, "20240702_add_plan_fields")
            
            # Verify the column was created correctly
            inspector = sa.inspect(db.engine)
            user_columns = {col["name"]: col for col in inspector.get_columns("users")}
            
            assert "free_alert_consumed" in user_columns
            assert user_columns["free_alert_consumed"]["nullable"] is False
            
            # Check that default value was applied
            with db.engine.begin() as conn:
                result = conn.execute(
                    sa.text(
                        """
                        SELECT free_alert_consumed 
                        FROM users 
                        WHERE email = 'test@example.com'
                        """
                    )
                ).fetchone()
                
                # Should be FALSE (0 in SQLite)
                assert result[0] == 0
