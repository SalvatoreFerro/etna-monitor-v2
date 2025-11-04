import os

import pytest
from sqlalchemy import text

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import app
from app.bootstrap import get_alembic_status
from app.models import db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.app_context():
        status = get_alembic_status(app)
        head = status.get("head_revision")
        with db.engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) NOT NULL)"
                )
            )
            conn.execute(text("DELETE FROM alembic_version"))
            if head:
                conn.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                    {"rev": head},
                )
            conn.commit()
    with app.test_client() as c:
        yield c

def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["ok"] is True
    assert "uptime_seconds" in payload
    assert "csv" in payload
    assert "premium_users" in payload
    assert payload["database"]["is_up_to_date"] is True


def test_healthz_debug_includes_db_status(client):
    app.config["DEBUG"] = True
    try:
        r = client.get("/healthz")
        assert r.status_code == 200
        payload = r.get_json()
        assert "db_status" in payload
        assert payload["db_status"]["is_up_to_date"] is True
    finally:
        app.config["DEBUG"] = False
