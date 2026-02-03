from datetime import datetime
from decimal import Decimal

import pytest

from app import create_app
from app.models import db
from app.models.cron_run import CronRun
from app.services.runlog_service import log_cron_run_external


@pytest.fixture
def app_with_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    csv_path = tmp_path / "curva.csv"
    csv_path.write_text("timestamp,value\n2024-01-01T00:00:00Z,1.25\n", encoding="utf-8")

    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "TESTING": True,
            "CRON_SECRET": "test-secret",
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_check_alerts_persists_cron_run(app_with_db, monkeypatch):
    def _fake_check(self, raise_on_error=True, **_kwargs):
        return {
            "sent": 0,
            "skipped": 0,
            "cooldown_skipped": 0,
            "skipped_by_reason": {},
            "reason": "completed",
        }

    monkeypatch.setattr("app.routes.internal.TelegramService.is_configured", lambda self: True)
    monkeypatch.setattr("app.routes.internal.TelegramService.check_and_send_alerts", _fake_check)

    client = app_with_db.test_client()
    response = client.post("/internal/cron/check-alerts?key=test-secret")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True

    with app_with_db.app_context():
        run = CronRun.query.filter_by(job_type="check_alerts").first()
        assert run is not None
        assert run.ok is True
        assert run.status == "success"
        assert run.reason == "completed"
        assert run.duration_ms is not None
        assert run.csv_path
        assert isinstance(run.created_at, datetime)
        assert isinstance(run.started_at, datetime)
        assert isinstance(run.finished_at, datetime)
        assert isinstance(run.diagnostic_json, dict)


def test_log_cron_run_external_sanitizes_json(tmp_path):
    db_path = tmp_path / "cron_runs.db"
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "TESTING": True,
        }
    )
    with app.app_context():
        db.create_all()

    payload = {
        "job_type": "csv_updater",
        "ok": True,
        "payload": {
            "ran_at": datetime(2024, 1, 1, 0, 0, 0),
            "amount": Decimal("12.5"),
            "data": b"\x01\x02",
            "tags": {"a", "b"},
        },
    }
    log_cron_run_external(payload, database_uri=f"sqlite:///{db_path}")

    with app.app_context():
        run = CronRun.query.filter_by(job_type="csv_updater").first()
        assert run is not None
        assert run.payload["ran_at"] == "2024-01-01T00:00:00"
        assert run.payload["amount"] == 12.5
        assert run.payload["data"] == "0102"
        assert sorted(run.payload["tags"]) == ["a", "b"]
