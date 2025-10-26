import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
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


def test_healthz_debug_includes_db_status(client):
    app.config["DEBUG"] = True
    try:
        r = client.get("/healthz")
        assert r.status_code == 200
        payload = r.get_json()
        assert "db_status" in payload
        assert payload["db_status"]["error"] is not None or payload["db_status"]["is_up_to_date"] in {True, False}
    finally:
        app.config["DEBUG"] = False
